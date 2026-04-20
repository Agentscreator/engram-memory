"""Workspace configuration management and invite key cryptography.

Handles:
- Reading/writing ~/.engram/workspace.json
- Team ID generation
- Invite key generation: self-contained encrypted tokens carrying db_url
- Invite key decoding: no shared secret needed, key is self-contained
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

WORKSPACE_PATH = Path.home() / ".engram" / "workspace.json"


_CREDENTIALS_PATH = Path.home() / ".engram" / "credentials"


@dataclass
class WorkspaceConfig:
    engram_id: str
    db_url: str = ""
    schema: str = "engram"
    anonymous_mode: bool = False
    anon_agents: bool = False
    key_generation: int = 0
    is_creator: bool = False
    display_name: str = ""
    description: str = ""
    server_url: str = ""
    invite_key: str = ""


def read_workspace() -> WorkspaceConfig | None:
    """Return the workspace config, or None if not yet configured."""
    if WORKSPACE_PATH.exists():
        try:
            data = json.loads(WORKSPACE_PATH.read_text())
            # Backward compatibility: add fields if missing
            defaults = {
                "schema": "engram",
                "key_generation": 0,
                "is_creator": False,
                "display_name": "",
                "description": "",
                "server_url": "",
            }
            for key, val in defaults.items():
                data.setdefault(key, val)
            return WorkspaceConfig(**data)
        except Exception:
            return None

    # Fall back to ENGRAM_DB_URL env var without a workspace file
    db_url = os.environ.get("ENGRAM_DB_URL", "")
    schema = os.environ.get("ENGRAM_SCHEMA", "engram")
    if db_url:
        return WorkspaceConfig(engram_id="local", db_url=db_url, schema=schema)

    # Fall back to ~/.engram/credentials (hosted/cloud users whose invite key
    # has no embedded db_url, so _join_workspace never writes workspace.json)
    return _read_credentials_as_workspace()


def _read_credentials_as_workspace() -> WorkspaceConfig | None:
    """Parse ~/.engram/credentials and return a hosted WorkspaceConfig, or None."""
    if not _CREDENTIALS_PATH.exists():
        return None
    creds: dict[str, str] = {}
    for line in _CREDENTIALS_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            creds[k.strip()] = v.strip()
    server_url = creds.get("ENGRAM_SERVER_URL", "")
    invite_key = creds.get("ENGRAM_INVITE_KEY", "")
    if not server_url and not invite_key:
        return None
    # Try to extract engram_id from the invite key payload
    engram_id = "hosted"
    if invite_key:
        try:
            payload = decode_invite_key(invite_key)
            engram_id = payload.get("engram_id", "hosted") or "hosted"
        except Exception:
            pass
    return WorkspaceConfig(engram_id=engram_id, server_url=server_url, invite_key=invite_key)


def write_workspace(config: WorkspaceConfig) -> None:
    """Persist workspace config to ~/.engram/workspace.json (mode 600)."""
    WORKSPACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKSPACE_PATH.write_text(json.dumps(asdict(config), indent=2))
    WORKSPACE_PATH.chmod(0o600)


def clear_workspace_config() -> None:
    """Remove the local workspace config file, effectively de-linking from the workspace."""
    if WORKSPACE_PATH.exists():
        WORKSPACE_PATH.unlink()


EDITABLE_CONFIG_KEYS = {"anonymous_mode", "anon_agents", "display_name", "description"}


def workspace_settings_dict(config: WorkspaceConfig) -> dict[str, Any]:
    """Return only the user-editable settings."""
    return {
        "anonymous_mode": config.anonymous_mode,
        "anon_agents": config.anon_agents,
        "display_name": config.display_name,
        "description": config.description,
    }


def read_workspace_settings() -> dict[str, Any]:
    """Return editable settings from ~/.engram/workspace.json."""
    if not WORKSPACE_PATH.exists():
        raise ValueError(f"No workspace config found at {WORKSPACE_PATH}")

    config = read_workspace()
    if config is None:
        raise ValueError(f"Failed to read workspace config at {WORKSPACE_PATH}")

    return workspace_settings_dict(config)


def _parse_bool(raw_value: str) -> bool:
    value = raw_value.strip().lower()

    if value in {"true", "1", "yes", "y", "on"}:
        return True
    if value in {"false", "0", "no", "n", "off"}:
        return False

    raise ValueError(f"Invalid boolean value: {raw_value}")


def parse_config_value(key: str, raw_value: str) -> Any:
    """Validate and coerce a raw CLI value for a supported config key."""
    if key not in EDITABLE_CONFIG_KEYS:
        allowed = ", ".join(sorted(EDITABLE_CONFIG_KEYS))
        raise ValueError(f"Unknown config key '{key}'. Allowed keys: {allowed}")

    if key in {"anonymous_mode", "anon_agents"}:
        return _parse_bool(raw_value)

    if key == "display_name":
        stripped = raw_value.strip()
        if not stripped:
            raise ValueError("display_name cannot be empty")
        return stripped

    if key == "description":
        return raw_value.strip()

    raise ValueError(f"Unsupported config key: {key}")


def set_workspace_setting(key: str, raw_value: str) -> WorkspaceConfig:
    """Update one editable setting in ~/.engram/workspace.json and persist it."""
    if not WORKSPACE_PATH.exists():
        raise ValueError(f"No workspace config found at {WORKSPACE_PATH}")

    config = read_workspace()
    if config is None:
        raise ValueError(f"Failed to read workspace config at {WORKSPACE_PATH}")

    value = parse_config_value(key, raw_value)
    setattr(config, key, value)
    write_workspace(config)
    return config


def is_configured() -> bool:
    """Return True if a workspace config exists or ENGRAM_DB_URL is set."""
    return (
        WORKSPACE_PATH.exists()
        or bool(os.environ.get("ENGRAM_DB_URL"))
        or _CREDENTIALS_PATH.exists()
    )


def is_team_mode() -> bool:
    """Return True if we should use PostgreSQL (db_url is set)."""
    cfg = read_workspace()
    if cfg and cfg.db_url:
        return True
    return bool(os.environ.get("ENGRAM_DB_URL"))


def get_db_url() -> str | None:
    """Return the database URL, preferring workspace.json over env var."""
    cfg = read_workspace()
    if cfg and cfg.db_url:
        return cfg.db_url
    return os.environ.get("ENGRAM_DB_URL") or None


# ── Team ID generation ───────────────────────────────────────────────


_TEAM_ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/1/0 to avoid confusion


def generate_team_id() -> str:
    """Generate a human-readable team ID like ENG-X7K2-P9M4."""
    p1 = "".join(secrets.choice(_TEAM_ID_CHARS) for _ in range(4))
    p2 = "".join(secrets.choice(_TEAM_ID_CHARS) for _ in range(4))
    return f"ENG-{p1}-{p2}"


# ── Invite key cryptography ──────────────────────────────────────────
#
# The invite key is a self-contained encrypted token. No shared secret
# is needed to decode it — the encryption key is embedded in the token.
#
# Token layout (before base64):
#   enc_key   [32 bytes]  randomly generated AES-256 key material
#   iv        [16 bytes]  random initialization vector
#   mac       [32 bytes]  HMAC-SHA256(enc_key, iv + ciphertext)
#   ciphertext [N bytes]  XOR-stream-encrypted JSON payload
#
# Stream cipher: keystream = SHA256(enc_key || iv || counter) repeated.
# HMAC authenticates the ciphertext — tampered tokens are rejected.
#
# The invite_keys table stores SHA256(enc_key) so the server can:
#   1. Validate uses_remaining and expiry from the database
#   2. Revoke a key before it expires
#   3. Decrement uses_remaining on each successful join


def _keystream(enc_key: bytes, iv: bytes, length: int) -> bytes:
    """Deterministic keystream derived from enc_key + iv."""
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(enc_key + iv + counter.to_bytes(4, "big")).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


def _xor(data: bytes, enc_key: bytes, iv: bytes) -> bytes:
    ks = _keystream(enc_key, iv, len(data))
    return bytes(a ^ b for a, b in zip(data, ks))


def generate_invite_key(
    db_url: str,
    engram_id: str,
    expires_days: int = 90,
    uses_remaining: int | None = 10,
    schema: str = "engram",
    key_generation: int = 0,
) -> tuple[str, str]:
    """Generate an invite key with db_url encrypted inside it.

    Returns:
        (invite_key, key_hash) where key_hash = SHA256(enc_key) in hex.
        Store key_hash in the invite_keys table for server-side validation.
    """
    enc_key = secrets.token_bytes(32)
    iv = secrets.token_bytes(16)

    payload = json.dumps(
        {
            "db_url": db_url,
            "engram_id": engram_id,
            "schema": schema,
            "expires_at": int(time.time()) + expires_days * 86400,
            "uses_remaining": uses_remaining,
            "created_at": int(time.time()),
            "key_generation": key_generation,
        }
    ).encode()

    ciphertext = _xor(payload, enc_key, iv)
    mac = hmac.new(enc_key, iv + ciphertext, hashlib.sha256).digest()

    token = enc_key + iv + mac + ciphertext
    b64 = base64.urlsafe_b64encode(token).rstrip(b"=").decode()
    key_hash = hashlib.sha256(enc_key).hexdigest()

    return f"ek_live_{b64}", key_hash


def decode_invite_key(invite_key: str) -> dict[str, Any]:
    """Decode and authenticate an invite key.

    No shared secret required — the enc_key is embedded in the token.
    Raises ValueError with a descriptive message on any failure.

    Returns payload dict: {db_url, engram_id, schema, expires_at, uses_remaining, created_at}
    """
    invite_key = "".join(
        invite_key.split()
    )  # strip all whitespace (handles copy-paste line breaks)
    if not invite_key.startswith("ek_live_"):
        raise ValueError("Invalid invite key format (must start with ek_live_)")

    b64 = invite_key[8:]
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding

    try:
        token = base64.urlsafe_b64decode(b64)
    except Exception:
        raise ValueError("Invalid invite key encoding")

    # Minimum: 32 enc_key + 16 iv + 32 mac = 80 bytes
    if len(token) < 81:
        raise ValueError("Invite key is too short — may be truncated")

    enc_key = token[:32]
    iv = token[32:48]
    mac = token[48:80]
    ciphertext = token[80:]

    # Authenticate before decrypting
    expected_mac = hmac.new(enc_key, iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_mac, mac):
        raise ValueError("Invite key authentication failed — key may be corrupted or tampered")

    # Decrypt
    try:
        payload_bytes = _xor(ciphertext, enc_key, iv)
        payload = json.loads(payload_bytes)
    except Exception:
        raise ValueError("Failed to decode invite key payload")

    # Check expiry
    if payload.get("expires_at", 0) < int(time.time()):
        raise ValueError("This invite key has expired")

    # Backward compatibility: add fields if missing (old keys)
    if "schema" not in payload:
        payload["schema"] = "engram"
    if "key_generation" not in payload:
        payload["key_generation"] = 0

    return payload


def invite_key_hash(invite_key: str) -> str:
    """Return the key_hash for looking up an invite key in the database.

    Extracts enc_key from the token and returns SHA256(enc_key) as hex.
    """
    invite_key = "".join(
        invite_key.split()
    )  # strip all whitespace (handles copy-paste line breaks)
    if not invite_key.startswith("ek_live_"):
        raise ValueError("Invalid invite key format")
    b64 = invite_key[8:]
    padding = 4 - len(b64) % 4
    if padding != 4:
        b64 += "=" * padding
    token = base64.urlsafe_b64decode(b64)
    enc_key = token[:32]
    return hashlib.sha256(enc_key).hexdigest()
