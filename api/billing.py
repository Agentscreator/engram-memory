"""Engram billing — commit-volume tiered pricing with Stripe subscriptions.

Plans
─────
  free     :   500 commits/month  — $0
  builder  :  5 000 commits/month — $12/mo
  team     : 25 000 commits/month — $39/mo
  scale    :100 000 commits/month — $99/mo

All plans include LLM suggestions and the forgetting-based conflict detection.

Overage (paid plans only): $0.015 / commit above tier limit, billed via
Stripe metered item at period end.

Stripe Price IDs are configured as environment variables so they can be
updated without a code deploy:
  STRIPE_PRICE_BUILDER   price_xxx for the Builder plan
  STRIPE_PRICE_TEAM      price_xxx for the Team plan
  STRIPE_PRICE_SCALE     price_xxx for the Scale plan

POST /billing/checkout   { engram_id, plan }  → Stripe Checkout URL
POST /billing/webhook                         → Stripe webhook handler
GET  /billing/portal     ?engram_id=…         → Stripe Customer Portal URL
GET  /billing/status     ?engram_id=…         → usage + plan status
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

# ── Plan definitions ─────────────────────────────────────────────────
# 'hobby' and 'pro' are legacy plan names — treated as 'free' and 'builder'.
PLANS: dict[str, dict] = {
    "free": {
        "name": "Free",
        "commits": 500,
        "price_usd": 0,
        "desc": "Personal use",
    },
    "builder": {
        "name": "Builder",
        "commits": 5_000,
        "price_usd": 12,
        "desc": "Solo developers",
    },
    "team": {
        "name": "Team",
        "commits": 25_000,
        "price_usd": 39,
        "desc": "Small teams",
    },
    "scale": {
        "name": "Scale",
        "commits": 100_000,
        "price_usd": 99,
        "desc": "Production",
    },
}

# Legacy plan aliases
_PLAN_ALIASES = {"hobby": "free", "pro": "builder"}

OVERAGE_PRICE_PER_COMMIT = 0.015  # $0.015 per commit above paid-tier limit

# Stripe Price IDs — set these in your environment after creating products in
# the Stripe dashboard (or via the Stripe CLI / API).
STRIPE_PRICES = {
    "builder": os.environ.get("STRIPE_PRICE_BUILDER", ""),
    "team": os.environ.get("STRIPE_PRICE_TEAM", ""),
    "scale": os.environ.get("STRIPE_PRICE_SCALE", ""),
}

_pool: Any = None


def canonical_plan(plan: str | None) -> str:
    """Normalise legacy plan names to canonical ones."""
    p = (plan or "free").lower()
    return _PLAN_ALIASES.get(p, p if p in PLANS else "free")


def plan_commit_limit(plan: str | None) -> int:
    return PLANS[canonical_plan(plan)]["commits"]


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
                f"""SELECT paused, plan, stripe_customer_id, stripe_subscription_id,
                           commit_count_month, commit_month, storage_bytes,
                           TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM') AS current_month
                    FROM {SCHEMA}.workspaces WHERE engram_id = $1""",
                engram_id,
            )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    if not ws:
        return JSONResponse({"error": "Workspace not found"}, status_code=404)

    plan = canonical_plan(ws["plan"])
    plan_info = PLANS[plan]
    commit_limit = plan_info["commits"]

    # Reset counter if month rolled over (read-only here; mcp.py resets on write)
    committed = ws["commit_count_month"] or 0
    if ws["commit_month"] != ws["current_month"]:
        committed = 0

    usage_pct = round(min(100.0, committed / commit_limit * 100), 1)

    return JSONResponse(
        {
            "engram_id": engram_id,
            "plan": plan,
            "plan_name": plan_info["name"],
            "paused": ws["paused"] or False,
            "commits_this_month": committed,
            "commit_limit": commit_limit,
            "usage_pct": usage_pct,
            "has_payment_method": bool(ws["stripe_customer_id"]),
            "has_subscription": bool(ws["stripe_subscription_id"]),
            "overage_price_per_commit": OVERAGE_PRICE_PER_COMMIT,
            "plans": {
                k: {
                    "name": v["name"],
                    "commits": v["commits"],
                    "price_usd": v["price_usd"],
                    "desc": v["desc"],
                }
                for k, v in PLANS.items()
            },
        }
    )


async def handle_checkout(request: Request) -> JSONResponse:
    """Create a Stripe Checkout Session (subscription) for a given plan."""
    session = _get_jwt_from_request(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    engram_id = (body.get("engram_id") or "").strip()
    plan = canonical_plan(body.get("plan") or "builder")

    if not engram_id:
        return JSONResponse({"error": "engram_id required"}, status_code=400)
    if plan not in ("builder", "team", "scale"):
        return JSONResponse(
            {"error": "Invalid plan — must be builder, team, or scale"}, status_code=400
        )
    if not STRIPE_SECRET_KEY:
        return JSONResponse({"error": "Stripe not configured"}, status_code=503)

    price_id = STRIPE_PRICES.get(plan, "")
    if not price_id:
        return JSONResponse(
            {
                "error": f"Stripe price for '{plan}' not configured (set STRIPE_PRICE_{plan.upper()})"
            },
            status_code=503,
        )

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
        try:
            pool = await _get_pool()
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
        except Exception:
            pass

    checkout_session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{APP_URL}/dashboard?billing=success&id={engram_id}",
        cancel_url=f"{APP_URL}/dashboard?billing=cancel&id={engram_id}",
        metadata={"engram_id": engram_id, "user_id": session["sub"], "plan": plan},
        subscription_data={"metadata": {"engram_id": engram_id, "plan": plan}},
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
    """Stripe webhook — handle subscription lifecycle."""
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

    etype = event["type"]

    # ── Subscription activated / updated ────────────────────────────
    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        sub = event["data"]["object"]
        engram_id = (sub.get("metadata") or {}).get("engram_id")
        plan = canonical_plan((sub.get("metadata") or {}).get("plan"))
        customer_id = sub.get("customer")
        sub_id = sub.get("id")
        status = sub.get("status", "")

        # Only activate on live/trialing subscriptions
        if engram_id and status in ("active", "trialing"):
            try:
                pool = await _get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        f"""UPDATE {SCHEMA}.workspaces
                               SET plan = $1, paused = false,
                                   stripe_customer_id = $2,
                                   stripe_subscription_id = $3
                             WHERE engram_id = $4""",
                        plan,
                        customer_id,
                        sub_id,
                        engram_id,
                    )
            except Exception:
                pass

    # ── Subscription cancelled / expired ────────────────────────────
    elif etype == "customer.subscription.deleted":
        sub = event["data"]["object"]
        engram_id = (sub.get("metadata") or {}).get("engram_id")
        if engram_id:
            try:
                pool = await _get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        f"""UPDATE {SCHEMA}.workspaces
                               SET plan = 'free', stripe_subscription_id = NULL
                             WHERE engram_id = $1""",
                        engram_id,
                    )
            except Exception:
                pass

    # ── Checkout session completed (subscription mode) ───────────────
    elif etype == "checkout.session.completed":
        cs = event["data"]["object"]
        if cs.get("mode") == "subscription":
            engram_id = (cs.get("metadata") or {}).get("engram_id")
            plan = canonical_plan((cs.get("metadata") or {}).get("plan"))
            customer_id = cs.get("customer")
            sub_id = cs.get("subscription")
            if engram_id:
                try:
                    pool = await _get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(
                            f"""UPDATE {SCHEMA}.workspaces
                                   SET plan = $1, paused = false,
                                       stripe_customer_id = $2,
                                       stripe_subscription_id = $3
                                 WHERE engram_id = $4""",
                            plan,
                            customer_id,
                            sub_id,
                            engram_id,
                        )
                except Exception:
                    pass

    # ── Invoice paid — clear paused flag ────────────────────────────
    elif etype == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")
        if customer_id:
            try:
                pool = await _get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        f"UPDATE {SCHEMA}.workspaces SET paused = false WHERE stripe_customer_id = $1",
                        customer_id,
                    )
            except Exception:
                pass

    # ── Invoice payment failed — pause workspace ─────────────────────
    elif etype == "invoice.payment_failed":
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")
        if customer_id:
            try:
                pool = await _get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        f"UPDATE {SCHEMA}.workspaces SET paused = true WHERE stripe_customer_id = $1",
                        customer_id,
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
        Route("/stripe/webhook", handle_webhook, methods=["POST"]),
        Route("/billing/{path:path}", handle_options, methods=["OPTIONS"]),
    ]
)
