"""Engram billing — Stripe integration + usage tracking.

Pricing (mirrors Neon + 20% markup):
  Free (Hobby): 512 MiB storage  (same as Neon's 0.5 GiB free tier)
  Paid:         $0.1424 / GiB-month  (Neon charges $0.1187; we charge 20% more)

When storage_bytes > HOBBY_LIMIT and no payment method on file → workspace paused.
User adds a card via Stripe Checkout (setup mode) → workspace unpaused.

POST /billing/checkout   { engram_id }  → Stripe Checkout Session URL
POST /billing/webhook                   → Stripe webhook handler
GET  /billing/portal     ?engram_id=… → Stripe Customer Portal URL
GET  /billing/status     ?engram_id=… → usage + billing status
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

DB_URL = os.environ.get("ENGRAM_DB_URL", "")
SCHEMA = "engram"
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_URL = os.environ.get("ENGRAM_APP_URL", "https://www.engram-memory.com")

# ── Pricing constants ────────────────────────────────────────────────
HOBBY_LIMIT_BYTES = 512 * 1024 * 1024  # 512 MiB (Neon free tier)
PRICE_PER_GIB_MONTH = 0.1424  # $0.1424/GiB-month (+20% over Neon)
PRICE_PER_BYTE_MONTH = PRICE_PER_GIB_MONTH / (1024**3)

_pool: Any = None


async def _get_pool() -> Any:
    global _pool
    if _pool is None:
        import asyncpg

        async def _set_path(c: Any) -> None:
            await c.execute(f"SET search_path TO {SCHEMA}, public")

        _pool = await asyncpg.create_pool(
            DB_URL, min_size=1, max_size=3, command_timeout=30, init=_set_path
        )
    return _pool


def _get_jwt_from_request(request: Request) -> dict | None:
    """Minimal JWT verifier — mirrors auth.py."""
    import base64
    import hmac
    import time

    token = request.cookies.get("engram_session")
    if not token:
        return None
    secret = (
        os.environ.get("ENGRAM_JWT_SECRET") or "engram-dev-secret-change-in-production"
    ).encode()
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header, body, sig = parts
    msg = f"{header}.{body}".encode()
    expected_sig = hmac.new(secret, msg, hashlib.sha256).digest()
    expected_b64 = base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()
    if not hmac.compare_digest(sig, expected_b64):
        return None
    padded = body + "=" * (4 - len(body) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    if payload.get("exp", 0) < int(time.time()):
        return None
    return payload


async def _user_owns_workspace(user_id: str, engram_id: str, pool: Any) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT 1 FROM {SCHEMA}.user_workspaces WHERE user_id = $1 AND engram_id = $2",
            user_id,
            engram_id,
        )
    return row is not None


# ── Usage helpers ────────────────────────────────────────────────────


def _monthly_charge_usd(storage_bytes: int) -> float:
    """Calculate monthly charge for storage above free tier."""
    overage = max(0, storage_bytes - HOBBY_LIMIT_BYTES)
    return round(overage * PRICE_PER_BYTE_MONTH, 4)


def _storage_pct(storage_bytes: int) -> float:
    return min(100.0, round(storage_bytes / HOBBY_LIMIT_BYTES * 100, 1))


# ── Handlers ─────────────────────────────────────────────────────────


async def handle_status(request: Request) -> JSONResponse:
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    engram_id = request.query_params.get("engram_id", "").strip()
    if not engram_id:
        return JSONResponse({"error": "engram_id required"}, status_code=400)

    try:
        pool = await _get_pool()
        if not await _user_owns_workspace(session["sub"], engram_id, pool):
            return JSONResponse({"error": "Workspace not found"}, status_code=404)

        async with pool.acquire() as conn:
            ws = await conn.fetchrow(
                f"SELECT paused, storage_bytes, plan, stripe_customer_id FROM {SCHEMA}.workspaces WHERE engram_id = $1",
                engram_id,
            )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    if not ws:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    storage = ws["storage_bytes"] or 0
    charge = _monthly_charge_usd(storage)
    return JSONResponse(
        {
            "engram_id": engram_id,
            "plan": ws["plan"] or "hobby",
            "paused": ws["paused"] or False,
            "storage_bytes": storage,
            "storage_mib": round(storage / (1024 * 1024), 2),
            "hobby_limit_mib": 512,
            "usage_pct": _storage_pct(storage),
            "has_payment_method": bool(ws["stripe_customer_id"]),
            "estimated_monthly_usd": charge,
            "price_per_gib_month": PRICE_PER_GIB_MONTH,
        }
    )


async def handle_checkout(request: Request) -> JSONResponse:
    """Create a Stripe Checkout Session (setup mode) to collect a payment method."""
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    engram_id = (body.get("engram_id") or "").strip()
    if not engram_id:
        return JSONResponse({"error": "engram_id required"}, status_code=400)

    if not STRIPE_SECRET_KEY:
        return JSONResponse({"error": "Stripe not configured"}, status_code=503)

    try:
        pool = await _get_pool()
        if not await _user_owns_workspace(session["sub"], engram_id, pool):
            return JSONResponse({"error": "Workspace not found"}, status_code=404)

        async with pool.acquire() as conn:
            ws = await conn.fetchrow(
                f"SELECT stripe_customer_id FROM {SCHEMA}.workspaces WHERE engram_id = $1",
                engram_id,
            )
            user = await conn.fetchrow(
                f"SELECT email, stripe_customer_id FROM {SCHEMA}.users WHERE id = $1",
                session["sub"],
            )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    import stripe

    stripe.api_key = STRIPE_SECRET_KEY

    # Reuse or create Stripe customer
    customer_id = (ws and ws["stripe_customer_id"]) or (user and user["stripe_customer_id"])
    if not customer_id:
        customer = stripe.Customer.create(
            email=user["email"] if user else None,
            metadata={"engram_id": engram_id, "user_id": session["sub"]},
        )
        customer_id = customer.id
        # Save customer id to user and workspace
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {SCHEMA}.users SET stripe_customer_id = $1 WHERE id = $2",
                customer_id,
                session["sub"],
            )
            await conn.execute(
                f"UPDATE {SCHEMA}.workspaces SET stripe_customer_id = $1 WHERE engram_id = $2",
                customer_id,
                engram_id,
            )

    checkout_session = stripe.checkout.Session.create(
        mode="setup",
        customer=customer_id,
        payment_method_types=["card"],
        success_url=f"{APP_URL}/dashboard?billing=success&id={engram_id}",
        cancel_url=f"{APP_URL}/dashboard?billing=cancel&id={engram_id}",
        metadata={"engram_id": engram_id, "user_id": session["sub"]},
    )

    return JSONResponse({"checkout_url": checkout_session.url})


async def handle_portal(request: Request) -> JSONResponse:
    """Create a Stripe Customer Portal session."""
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    engram_id = request.query_params.get("engram_id", "").strip()
    if not engram_id:
        return JSONResponse({"error": "engram_id required"}, status_code=400)

    if not STRIPE_SECRET_KEY:
        return JSONResponse({"error": "Stripe not configured"}, status_code=503)

    try:
        pool = await _get_pool()
        if not await _user_owns_workspace(session["sub"], engram_id, pool):
            return JSONResponse({"error": "Workspace not found"}, status_code=404)

        async with pool.acquire() as conn:
            ws = await conn.fetchrow(
                f"SELECT stripe_customer_id FROM {SCHEMA}.workspaces WHERE engram_id = $1",
                engram_id,
            )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    if not ws or not ws["stripe_customer_id"]:
        return JSONResponse({"error": "No payment method on file"}, status_code=404)

    import stripe

    stripe.api_key = STRIPE_SECRET_KEY

    portal = stripe.billing_portal.Session.create(
        customer=ws["stripe_customer_id"],
        return_url=f"{APP_URL}/dashboard?id={engram_id}",
    )
    return JSONResponse({"portal_url": portal.url})


async def handle_webhook(request: Request) -> Response:
    """Stripe webhook — handle payment method setup completion."""
    if not STRIPE_WEBHOOK_SECRET:
        return Response("Webhook secret not configured", status_code=503)

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    import stripe

    stripe.api_key = STRIPE_SECRET_KEY

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        return Response("Invalid signature", status_code=400)

    if event["type"] == "setup_intent.succeeded":
        setup_intent = event["data"]["object"]
        engram_id = (setup_intent.get("metadata") or {}).get("engram_id")
        customer_id = setup_intent.get("customer")

        if engram_id and customer_id:
            try:
                pool = await _get_pool()
                async with pool.acquire() as conn:
                    # Unpause workspace and record payment method
                    await conn.execute(
                        f"""UPDATE {SCHEMA}.workspaces
                           SET paused = false, stripe_customer_id = $1, plan = 'pro'
                           WHERE engram_id = $2""",
                        customer_id,
                        engram_id,
                    )
            except Exception:
                pass  # Log in production

    elif event["type"] == "checkout.session.completed":
        cs = event["data"]["object"]
        if cs.get("mode") == "setup":
            engram_id = (cs.get("metadata") or {}).get("engram_id")
            customer_id = cs.get("customer")
            if engram_id and customer_id:
                try:
                    pool = await _get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(
                            f"""UPDATE {SCHEMA}.workspaces
                               SET paused = false, stripe_customer_id = $1, plan = 'pro'
                               WHERE engram_id = $2""",
                            customer_id,
                            engram_id,
                        )
                except Exception:
                    pass

    return Response("ok", status_code=200)


async def handle_options(request: Request) -> Response:
    return Response(
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
    )


app = Starlette(
    routes=[
        Route("/billing/status", handle_status, methods=["GET"]),
        Route("/billing/checkout", handle_checkout, methods=["POST"]),
        Route("/billing/portal", handle_portal, methods=["GET"]),
        Route("/billing/webhook", handle_webhook, methods=["POST"]),
        Route("/stripe/webhook", handle_webhook, methods=["POST"]),  # canonical Stripe URL
        Route("/billing/{path:path}", handle_options, methods=["OPTIONS"]),
    ]
)
