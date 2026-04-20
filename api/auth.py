"""Engram user auth — signup, login, logout, me, workspace linking.

POST /auth/signup              { email, password }
POST /auth/login               { email, password }
POST /auth/logout
GET  /auth/me                  → current user + workspaces
POST /auth/connect-workspace   { engram_id, invite_key } — link workspace to account
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

DB_URL = os.environ.get("ENGRAM_DB_URL", "")
SCHEMA = "engram"
JWT_SECRET = os.environ.get("ENGRAM_JWT_SECRET", "")

_pool: Any = None

# Schema-qualified DDL so table creation never relies on search_path being set.
# No FK constraints — avoids ordering issues between auth.py and mcp.py.
_AUTH_SCHEMA_STMTS = [
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.workspaces (
        engram_id          TEXT PRIMARY KEY,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        anonymous_mode     BOOLEAN     NOT NULL DEFAULT false,
        anon_agents        BOOLEAN     NOT NULL DEFAULT false,
        key_generation     INTEGER     NOT NULL DEFAULT 0,
        paused             BOOLEAN     NOT NULL DEFAULT false,
        storage_bytes      BIGINT      NOT NULL DEFAULT 0,
        plan               TEXT        NOT NULL DEFAULT 'free',
        stripe_customer_id TEXT,
        display_name       TEXT
    )""",
    f"ALTER TABLE {SCHEMA}.workspaces ADD COLUMN IF NOT EXISTS display_name TEXT",
    f"ALTER TABLE {SCHEMA}.workspaces ADD COLUMN IF NOT EXISTS commit_count_month INTEGER NOT NULL DEFAULT 0",
    f"ALTER TABLE {SCHEMA}.workspaces ADD COLUMN IF NOT EXISTS commit_month TEXT",
    f"ALTER TABLE {SCHEMA}.workspaces ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.users (
        id                 TEXT PRIMARY KEY,
        email              TEXT UNIQUE NOT NULL,
        password_hash      TEXT NOT NULL,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        stripe_customer_id TEXT
    )""",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.user_workspaces (
        user_id   TEXT NOT NULL,
        engram_id TEXT NOT NULL,
        role      TEXT NOT NULL DEFAULT 'owner',
        PRIMARY KEY (user_id, engram_id)
    )""",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.invite_keys (
        key_hash       TEXT PRIMARY KEY,
        engram_id      TEXT NOT NULL,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at     TIMESTAMPTZ,
        uses_remaining INTEGER
    )""",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.workspace_keys (
        engram_id     TEXT PRIMARY KEY,
        pin_salt      TEXT NOT NULL,
        encrypted_key TEXT NOT NULL
    )""",
    # Indexes — created after tables so IF NOT EXISTS is safe on re-boot
    f"CREATE INDEX IF NOT EXISTS idx_uw_user_id ON {SCHEMA}.user_workspaces(user_id)",
    f"CREATE INDEX IF NOT EXISTS idx_facts_ws ON {SCHEMA}.facts(workspace_id)",
    f"CREATE INDEX IF NOT EXISTS idx_conflicts_ws ON {SCHEMA}.conflicts(workspace_id)",
    f"CREATE INDEX IF NOT EXISTS idx_agents_ws ON {SCHEMA}.agents(workspace_id)",
]


async def _get_pool() -> Any:
    global _pool
    if not DB_URL:
        raise RuntimeError("ENGRAM_DB_URL environment variable is not set")
    if _pool is None:
        import asyncpg

        async def _set_path(c: Any) -> None:
            await c.execute(f"SET search_path TO {SCHEMA}, public")

        # 1. Create the schema namespace
        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        finally:
            await conn.close()

        # 2. Create the pool (login works from this point on)
        _pool = await asyncpg.create_pool(
            DB_URL, min_size=1, max_size=3, command_timeout=30, init=_set_path
        )

        # 3. Bootstrap tables — schema-qualified so search_path doesn't matter.
        #    Run inside a single connection so all tables are created atomically.
        async with _pool.acquire() as conn:
            await conn.execute(f"SET search_path TO {SCHEMA}, public")
            for stmt in _AUTH_SCHEMA_STMTS:
                try:
                    await conn.execute(stmt)
                except Exception as exc:
                    import sys

                    print(f"[auth] bootstrap warning: {exc}", file=sys.stderr)

    return _pool


# ── Password hashing (PBKDF2, no external deps) ──────────────────────


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2:sha256:260000:{salt}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, algo, iters, salt, dk_hex = stored.split(":")
        dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ── JWT (HMAC-SHA256, no external deps) ─────────────────────────────


def _jwt_secret() -> bytes:
    secret = JWT_SECRET or os.environ.get("ENGRAM_JWT_SECRET", "")
    if not secret:
        # Fallback — sessions won't survive restarts, but won't crash
        return b"engram-dev-secret-change-in-production"
    return secret.encode()


def _create_jwt(user_id: str, email: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload_bytes = json.dumps(
        {
            "sub": user_id,
            "email": email,
            "exp": int(time.time()) + 86400 * 30,  # 30 days
        }
    ).encode()
    body = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    msg = f"{header}.{body}".encode()
    sig = hmac.new(_jwt_secret(), msg, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{header}.{body}.{sig_b64}"


def _verify_jwt(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    header, body, sig = parts
    msg = f"{header}.{body}".encode()
    expected_sig = hmac.new(_jwt_secret(), msg, hashlib.sha256).digest()
    expected_b64 = base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()
    if not hmac.compare_digest(sig, expected_b64):
        raise ValueError("Invalid token signature")
    # Pad body for base64 decode
    padded = body + "=" * (4 - len(body) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    if payload.get("exp", 0) < int(time.time()):
        raise ValueError("Token expired")
    return payload


def _get_jwt_from_request(request: Request) -> dict | None:
    token = request.cookies.get("engram_session")
    if not token:
        return None
    try:
        return _verify_jwt(token)
    except Exception:
        return None


def _set_session_cookie(response: Response, user_id: str, email: str) -> None:
    token = _create_jwt(user_id, email)
    response.set_cookie(
        "engram_session",
        token,
        max_age=86400 * 30,
        httponly=True,
        samesite="lax",
        secure=True,  # Vercel serves over HTTPS
        path="/",
    )


# ── Invite key verification (mirrored from workspace.py) ─────────────


def _decode_invite_key(invite_key: str) -> dict[str, Any]:
    if not invite_key.startswith("ek_live_"):
        raise ValueError("Invalid invite key format")
    b64 = invite_key[8:]
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    token = base64.urlsafe_b64decode(b64)
    if len(token) < 81:
        raise ValueError("Invite key too short")
    enc_key = token[:32]
    iv = token[32:48]
    mac = token[48:80]
    ciphertext = token[80:]

    def _keystream(length: int) -> bytes:
        stream = bytearray()
        counter = 0
        while len(stream) < length:
            block = hashlib.sha256(enc_key + iv + counter.to_bytes(4, "big")).digest()
            stream.extend(block)
            counter += 1
        return bytes(stream[:length])

    ks = _keystream(len(ciphertext))
    decrypted = bytes(a ^ b for a, b in zip(ciphertext, ks))
    expected_mac = hmac.new(enc_key, iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_mac, mac):
        raise ValueError("Invite key authentication failed")
    payload = json.loads(decrypted)
    if payload.get("expires_at", 0) < int(time.time()):
        raise ValueError("Invite key has expired")
    return payload


def _invite_key_hash(invite_key: str) -> str:
    b64 = invite_key[8:]
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    token = base64.urlsafe_b64decode(b64)
    return hashlib.sha256(token[:32]).hexdigest()


# ── Handlers ─────────────────────────────────────────────────────────


async def handle_signup(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or "@" not in email:
        return JSONResponse({"error": "Valid email required"}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters"}, status_code=400)

    try:
        pool = await _get_pool()
    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    user_id = f"usr_{uuid.uuid4().hex[:16]}"
    password_hash = _hash_password(password)

    try:
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(f"SELECT id FROM {SCHEMA}.users WHERE email = $1", email)
            if existing:
                return JSONResponse({"error": "Email already registered"}, status_code=409)
            await conn.execute(
                f"INSERT INTO {SCHEMA}.users (id, email, password_hash) VALUES ($1, $2, $3)",
                user_id,
                email,
                password_hash,
            )
    except Exception as exc:
        return JSONResponse({"error": f"Signup failed: {exc}"}, status_code=500)

    resp = JSONResponse({"user_id": user_id, "email": email})
    _set_session_cookie(resp, user_id, email)
    return resp


async def handle_login(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return JSONResponse({"error": "Email and password required"}, status_code=400)

    try:
        pool = await _get_pool()
    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT id, password_hash FROM {SCHEMA}.users WHERE email = $1", email
            )
    except Exception as exc:
        return JSONResponse({"error": f"Login failed: {exc}"}, status_code=500)

    if not row or not _verify_password(password, row["password_hash"]):
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)

    resp = JSONResponse({"user_id": row["id"], "email": email})
    _set_session_cookie(resp, row["id"], email)
    return resp


async def handle_logout(request: Request) -> JSONResponse:
    resp = JSONResponse({"status": "logged_out"})
    resp.delete_cookie("engram_session", path="/")
    return resp


async def handle_me(request: Request) -> JSONResponse:
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                f"SELECT id, email, stripe_customer_id, created_at FROM {SCHEMA}.users WHERE id = $1",
                session["sub"],
            )
            if not user:
                return JSONResponse({"error": "User not found"}, status_code=404)

            workspaces = await conn.fetch(
                f"""SELECT uw.engram_id, uw.role,
                          w.paused, w.storage_bytes, w.plan, w.stripe_customer_id AS ws_stripe_id,
                          w.created_at AS ws_created_at, w.display_name
                   FROM {SCHEMA}.user_workspaces uw
                   LEFT JOIN {SCHEMA}.workspaces w ON w.engram_id = uw.engram_id
                   WHERE uw.user_id = $1
                   ORDER BY w.created_at DESC""",
                session["sub"],
            )
    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    def _ser(v: Any) -> Any:
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v

    ws_list = [{k: _ser(v) for k, v in dict(r).items()} for r in workspaces]
    return JSONResponse(
        {
            "user_id": user["id"],
            "email": user["email"],
            "workspaces": ws_list,
        },
        headers={"Cache-Control": "private, max-age=30"},
    )


async def handle_connect_workspace(request: Request) -> JSONResponse:
    """Link an existing workspace to the logged-in user's account."""
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    engram_id = (body.get("engram_id") or "").strip()
    invite_key = (body.get("invite_key") or "").strip()

    if not engram_id or not invite_key:
        return JSONResponse({"error": "engram_id and invite_key required"}, status_code=400)

    # Verify invite key
    try:
        payload = _decode_invite_key(invite_key)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)

    if payload.get("engram_id") != engram_id:
        return JSONResponse({"error": "Invite key does not match workspace ID"}, status_code=401)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # Verify key exists in DB
            key_hash = _invite_key_hash(invite_key)
            key_row = await conn.fetchrow(
                f"SELECT uses_remaining FROM {SCHEMA}.invite_keys WHERE key_hash = $1 AND engram_id = $2",
                key_hash,
                engram_id,
            )
            if not key_row:
                return JSONResponse({"error": "Invalid or revoked invite key"}, status_code=401)

            # Link workspace to user
            await conn.execute(
                f"""INSERT INTO {SCHEMA}.user_workspaces (user_id, engram_id, role)
                   VALUES ($1, $2, 'owner')
                   ON CONFLICT (user_id, engram_id) DO NOTHING""",
                session["sub"],
                engram_id,
            )
    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    return JSONResponse({"status": "connected", "engram_id": engram_id})


# ── PIN-encrypted invite key helpers ─────────────────────────────────


def _xor_stream(data: bytes, key: bytes) -> bytes:
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        block = hashlib.sha256(key + counter.to_bytes(4, "big")).digest()
        stream.extend(block)
        counter += 1
    ks = bytes(stream[: len(data)])
    return bytes(a ^ b for a, b in zip(data, ks))


def _encrypt_invite_key(invite_key: str, pin: str) -> tuple[str, str]:
    """Encrypt invite key with a PIN. Returns (salt_hex, encrypted_hex)."""
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 260_000, dklen=32)
    encrypted = _xor_stream(invite_key.encode(), derived)
    return salt.hex(), encrypted.hex()


def _decrypt_invite_key(pin: str, salt_hex: str, encrypted_hex: str) -> str:
    """Decrypt invite key with a PIN."""
    salt = bytes.fromhex(salt_hex)
    encrypted = bytes.fromhex(encrypted_hex)
    derived = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 260_000, dklen=32)
    return _xor_stream(encrypted, derived).decode()


# ── Workspace init (mirrors mcp.py _tool_init) ───────────────────────


def _xor_cipher(data: bytes, enc_key: bytes, iv: bytes) -> bytes:
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        block = hashlib.sha256(enc_key + iv + counter.to_bytes(4, "big")).digest()
        stream.extend(block)
        counter += 1
    ks = bytes(stream[: len(data)])
    return bytes(a ^ b for a, b in zip(data, ks))


def _generate_team_id() -> str:
    import random
    import string

    chars = string.ascii_uppercase + string.digits
    part = lambda n: "".join(random.choices(chars, k=n))  # noqa: E731
    return f"ENG-{part(4)}-{part(4)}"


def _generate_invite_key(
    engram_id: str, expires_days: int = 3650, uses: int = 1000
) -> tuple[str, str]:
    import json as _json
    import time as _time

    enc_key = secrets.token_bytes(32)
    iv = secrets.token_bytes(16)
    payload = _json.dumps(
        {"engram_id": engram_id, "expires_at": int(_time.time()) + expires_days * 86400}
    ).encode()
    ciphertext = _xor_cipher(payload, enc_key, iv)
    mac = hmac.new(enc_key, iv + ciphertext, hashlib.sha256).digest()
    token = enc_key + iv + mac + ciphertext
    b64 = base64.urlsafe_b64encode(token).rstrip(b"=").decode()
    key_hash = hashlib.sha256(enc_key).hexdigest()
    return f"ek_live_{b64}", key_hash


# ── Handlers ──────────────────────────────────────────────────────────


async def handle_create_workspace(request: Request) -> JSONResponse:
    """Create a new Engram workspace and protect its invite key with a PIN."""
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    pin = str(body.get("pin") or "").strip()
    if not pin.isdigit() or len(pin) != 4:
        return JSONResponse({"error": "PIN must be exactly 4 digits"}, status_code=400)

    display_name = (body.get("display_name") or "").strip()[:80] or None

    try:
        pool = await _get_pool()
    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    import time as _time

    engram_id = _generate_team_id()
    invite_key, key_hash = _generate_invite_key(engram_id)
    expires_ts = _time.time() + 3650 * 86400
    pin_salt, encrypted_key = _encrypt_invite_key(invite_key, pin)

    import datetime as _dt

    expires_dt = _dt.datetime.fromtimestamp(expires_ts, tz=_dt.timezone.utc)

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    f"INSERT INTO {SCHEMA}.workspaces (engram_id, display_name) VALUES ($1, $2)",
                    engram_id,
                    display_name,
                )
                await conn.execute(
                    f"""INSERT INTO {SCHEMA}.invite_keys (key_hash, engram_id, expires_at, uses_remaining)
                       VALUES ($1, $2, $3, $4)""",
                    key_hash,
                    engram_id,
                    expires_dt,
                    1000,
                )
                await conn.execute(
                    f"""INSERT INTO {SCHEMA}.workspace_keys (engram_id, pin_salt, encrypted_key)
                       VALUES ($1, $2, $3)""",
                    engram_id,
                    pin_salt,
                    encrypted_key,
                )
                await conn.execute(
                    f"""INSERT INTO {SCHEMA}.user_workspaces (user_id, engram_id, role)
                       VALUES ($1, $2, 'owner')""",
                    session["sub"],
                    engram_id,
                )
    except Exception as exc:
        return JSONResponse({"error": f"Failed to create workspace: {exc}"}, status_code=500)

    return JSONResponse({"engram_id": engram_id, "invite_key": invite_key})


async def handle_invite_key(request: Request) -> JSONResponse:
    """Return the stored invite key after PIN verification."""
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    engram_id = (body.get("engram_id") or "").strip()
    pin = str(body.get("pin") or "").strip()

    if not engram_id or not pin:
        return JSONResponse({"error": "engram_id and pin required"}, status_code=400)
    if not pin.isdigit() or len(pin) != 4:
        return JSONResponse({"error": "Invalid PIN"}, status_code=400)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            owns = await conn.fetchrow(
                f"SELECT 1 FROM {SCHEMA}.user_workspaces WHERE user_id = $1 AND engram_id = $2",
                session["sub"],
                engram_id,
            )
            if not owns:
                return JSONResponse(
                    {"error": "Workspace not found or access denied"}, status_code=403
                )

            row = await conn.fetchrow(
                f"SELECT pin_salt, encrypted_key FROM {SCHEMA}.workspace_keys WHERE engram_id = $1",
                engram_id,
            )
    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    if not row:
        return JSONResponse(
            {
                "error": "No invite key stored for this workspace. It may have been created outside the dashboard."
            },
            status_code=404,
        )

    try:
        invite_key = _decrypt_invite_key(pin, row["pin_salt"], row["encrypted_key"])
    except Exception:
        return JSONResponse({"error": "Incorrect PIN"}, status_code=401)

    # Validate the decrypted key looks sane
    if not invite_key.startswith("ek_live_"):
        return JSONResponse({"error": "Incorrect PIN"}, status_code=401)

    return JSONResponse({"invite_key": invite_key})


async def handle_reset_invite_key(request: Request) -> JSONResponse:
    """Revoke all existing invite keys and issue a new one (PIN required)."""
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    engram_id = (body.get("engram_id") or "").strip()
    pin = str(body.get("pin") or "").strip()

    if not engram_id or not pin:
        return JSONResponse({"error": "engram_id and pin required"}, status_code=400)
    if not pin.isdigit() or len(pin) != 4:
        return JSONResponse({"error": "Invalid PIN"}, status_code=400)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            owns = await conn.fetchrow(
                f"SELECT 1 FROM {SCHEMA}.user_workspaces WHERE user_id = $1 AND engram_id = $2",
                session["sub"],
                engram_id,
            )
            if not owns:
                return JSONResponse(
                    {"error": "Workspace not found or access denied"}, status_code=403
                )

            row = await conn.fetchrow(
                f"SELECT pin_salt, encrypted_key FROM {SCHEMA}.workspace_keys WHERE engram_id = $1",
                engram_id,
            )
            if not row:
                return JSONResponse(
                    {"error": "No key record found for this workspace."}, status_code=404
                )

            # Verify PIN before doing anything destructive
            try:
                existing = _decrypt_invite_key(pin, row["pin_salt"], row["encrypted_key"])
            except Exception:
                return JSONResponse({"error": "Incorrect PIN"}, status_code=401)
            if not existing.startswith("ek_live_"):
                return JSONResponse({"error": "Incorrect PIN"}, status_code=401)

            import datetime as _dt
            import time as _time

            new_key, new_hash = _generate_invite_key(engram_id)
            expires_dt = _dt.datetime.fromtimestamp(
                _time.time() + 3650 * 86400, tz=_dt.timezone.utc
            )
            new_salt, new_encrypted = _encrypt_invite_key(new_key, pin)

            async with conn.transaction():
                # Revoke all existing keys for this workspace
                await conn.execute(
                    f"DELETE FROM {SCHEMA}.invite_keys WHERE engram_id = $1", engram_id
                )
                # Insert the new key
                await conn.execute(
                    f"""INSERT INTO {SCHEMA}.invite_keys
                        (key_hash, engram_id, expires_at, uses_remaining)
                        VALUES ($1, $2, $3, $4)""",
                    new_hash,
                    engram_id,
                    expires_dt,
                    1000,
                )
                # Re-encrypt and store the new key with the same PIN
                await conn.execute(
                    f"""UPDATE {SCHEMA}.workspace_keys
                        SET pin_salt = $1, encrypted_key = $2
                        WHERE engram_id = $3""",
                    new_salt,
                    new_encrypted,
                    engram_id,
                )
    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    return JSONResponse({"status": "reset", "invite_key": new_key})


async def handle_options(request: Request) -> Response:
    return Response(
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
    )


async def handle_rename_workspace(request: Request) -> JSONResponse:
    """Rename a workspace the logged-in user owns. POST {engram_id, display_name}."""
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    engram_id = (body.get("engram_id") or "").strip()
    display_name = (body.get("display_name") or "").strip()

    if not engram_id:
        return JSONResponse({"error": "engram_id is required"}, status_code=400)
    if not display_name:
        return JSONResponse({"error": "display_name cannot be empty"}, status_code=400)
    if len(display_name) > 80:
        return JSONResponse(
            {"error": "display_name must be 80 characters or fewer"}, status_code=400
        )

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            owns = await conn.fetchrow(
                f"SELECT 1 FROM {SCHEMA}.user_workspaces WHERE user_id = $1 AND engram_id = $2",
                session["sub"],
                engram_id,
            )
            if not owns:
                return JSONResponse(
                    {"error": "Workspace not found or access denied"}, status_code=403
                )
            await conn.execute(
                f"UPDATE {SCHEMA}.workspaces SET display_name = $1 WHERE engram_id = $2",
                display_name,
                engram_id,
            )
    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    return JSONResponse({"status": "ok", "engram_id": engram_id, "display_name": display_name})


async def handle_leave_workspace(request: Request) -> JSONResponse:
    """Remove the logged-in user from a workspace. POST {engram_id}.
    If the user is the last member, the workspace and all its data are deleted.
    """
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    engram_id = (body.get("engram_id") or "").strip()
    if not engram_id:
        return JSONResponse({"error": "engram_id is required"}, status_code=400)

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            owns = await conn.fetchrow(
                f"SELECT 1 FROM {SCHEMA}.user_workspaces WHERE user_id = $1 AND engram_id = $2",
                session["sub"],
                engram_id,
            )
            if not owns:
                return JSONResponse(
                    {"error": "Workspace not found or access denied"}, status_code=403
                )

            await conn.execute(
                f"DELETE FROM {SCHEMA}.user_workspaces WHERE user_id = $1 AND engram_id = $2",
                session["sub"],
                engram_id,
            )

            remaining = await conn.fetchval(
                f"SELECT COUNT(*) FROM {SCHEMA}.user_workspaces WHERE engram_id = $1",
                engram_id,
            )
            if remaining == 0:
                for table in ("facts", "conflicts"):
                    await conn.execute(
                        f"DELETE FROM {SCHEMA}.{table} WHERE workspace_id = $1", engram_id
                    )
                await conn.execute(
                    f"DELETE FROM {SCHEMA}.invite_keys WHERE engram_id = $1", engram_id
                )
                await conn.execute(
                    f"DELETE FROM {SCHEMA}.workspace_keys WHERE engram_id = $1", engram_id
                )
                await conn.execute(
                    f"DELETE FROM {SCHEMA}.workspaces WHERE engram_id = $1", engram_id
                )
    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    return JSONResponse({"status": "ok", "engram_id": engram_id})


async def handle_delete_account(request: Request) -> JSONResponse:
    """Permanently delete the authenticated user's account. POST (no body required).

    - Removes the user from all workspaces they are a member of.
    - For each workspace where they were the last member, deletes the workspace
      and all its facts, conflicts, and keys.
    - Finally deletes the user row and clears the session cookie.
    """
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    user_id = session["sub"]
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # Find all workspaces this user belongs to
            rows = await conn.fetch(
                f"SELECT engram_id FROM {SCHEMA}.user_workspaces WHERE user_id = $1",
                user_id,
            )
            for row in rows:
                eid = row["engram_id"]
                await conn.execute(
                    f"DELETE FROM {SCHEMA}.user_workspaces WHERE user_id = $1 AND engram_id = $2",
                    user_id,
                    eid,
                )
                remaining = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {SCHEMA}.user_workspaces WHERE engram_id = $1",
                    eid,
                )
                if remaining == 0:
                    for table in ("facts", "conflicts"):
                        await conn.execute(
                            f"DELETE FROM {SCHEMA}.{table} WHERE workspace_id = $1", eid
                        )
                    await conn.execute(
                        f"DELETE FROM {SCHEMA}.invite_keys WHERE engram_id = $1", eid
                    )
                    await conn.execute(
                        f"DELETE FROM {SCHEMA}.workspace_keys WHERE engram_id = $1", eid
                    )
                    await conn.execute(f"DELETE FROM {SCHEMA}.workspaces WHERE engram_id = $1", eid)

            # Delete the user record
            await conn.execute(f"DELETE FROM {SCHEMA}.users WHERE id = $1", user_id)

    except Exception as exc:
        return JSONResponse({"error": f"Database error: {exc}"}, status_code=500)

    resp = JSONResponse({"status": "deleted"})
    resp.delete_cookie("engram_session", path="/")
    return resp


app = Starlette(
    routes=[
        Route("/auth/signup", handle_signup, methods=["POST"]),
        Route("/auth/login", handle_login, methods=["POST"]),
        Route("/auth/logout", handle_logout, methods=["POST"]),
        Route("/auth/me", handle_me, methods=["GET"]),
        Route("/auth/connect-workspace", handle_connect_workspace, methods=["POST"]),
        Route("/auth/create-workspace", handle_create_workspace, methods=["POST"]),
        Route("/auth/invite-key", handle_invite_key, methods=["POST"]),
        Route("/auth/rename-workspace", handle_rename_workspace, methods=["POST"]),
        Route("/auth/leave-workspace", handle_leave_workspace, methods=["POST"]),
        Route("/auth/reset-invite-key", handle_reset_invite_key, methods=["POST"]),
        Route("/auth/delete-account", handle_delete_account, methods=["POST"]),
        Route("/auth/{path:path}", handle_options, methods=["OPTIONS"]),
    ]
)
