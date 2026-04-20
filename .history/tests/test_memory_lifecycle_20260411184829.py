"""Lifecycle tests for ephemeral memory: TTL expiry, reinforcement, promotion, durability.

These tests validate the README claim that ephemeral facts expire after TTL,
that reinforcement (auto-promotion via query hits) prevents expiry, that
explicit promotion overrides TTL, and that durable facts never disappear
via the TTL sweep.

Time is controlled by passing a synthetic ``as_of`` timestamp to
``expire_ttl_facts`` instead of sleeping — no wall-clock delays needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engram.engine import EngramEngine
from engram.storage import Storage


def _future_iso(days: int) -> str:
    """Return an ISO timestamp ``days`` into the future."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# ── Ephemeral expiry ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ephemeral_fact_is_immediately_retrievable(engine: EngramEngine, storage: Storage):
    """An ephemeral fact is present right after commit."""
    result = await engine.commit(
        content="Scratchpad: auth warm-up takes 3 seconds",
        scope="lifecycle",
        confidence=0.6,
        agent_id="agent-1",
        durability="ephemeral",
        ttl_days=1,
    )
    fact = await storage.get_fact_by_id(result["fact_id"])
    assert fact is not None
    assert fact["valid_until"] is None


@pytest.mark.asyncio
async def test_ephemeral_fact_expires_after_ttl(engine: EngramEngine, storage: Storage):
    """An ephemeral fact is gone once the TTL sweep runs past its expiry."""
    result = await engine.commit(
        content="Scratchpad: auth warm-up takes 3 seconds",
        scope="lifecycle",
        confidence=0.6,
        agent_id="agent-1",
        durability="ephemeral",
        ttl_days=1,
    )
    fact_id = result["fact_id"]

    expired = await storage.expire_ttl_facts(as_of=_future_iso(2))
    assert expired >= 1

    fact = await storage.get_fact_by_id(fact_id)
    assert fact["valid_until"] is not None


# ── Reinforcement prevents expiry ───────────────────────────────────


@pytest.mark.asyncio
async def test_reinforcement_marks_fact_as_promotable(engine: EngramEngine, storage: Storage):
    """After two query hits, an ephemeral fact becomes promotable."""
    result = await engine.commit(
        content="Scratchpad: connection pool size is 10",
        scope="lifecycle",
        confidence=0.7,
        agent_id="agent-1",
        durability="ephemeral",
        ttl_days=1,
    )
    fact_id = result["fact_id"]

    await storage.increment_query_hits([fact_id])
    await storage.increment_query_hits([fact_id])

    promotable = await storage.get_promotable_ephemeral_facts(min_hits=2)
    assert any(p["id"] == fact_id for p in promotable)


@pytest.mark.asyncio
async def test_reinforcement_then_auto_promote_prevents_expiry(
    engine: EngramEngine, storage: Storage
):
    """An ephemeral fact that reaches the query-hit threshold and is promoted survives TTL."""
    result = await engine.commit(
        content="Scratchpad: connection pool size is 10",
        scope="lifecycle",
        confidence=0.7,
        agent_id="agent-1",
        durability="ephemeral",
        ttl_days=1,
    )
    fact_id = result["fact_id"]

    # Simulate two query hits — the reinforcement heuristic threshold
    await storage.increment_query_hits([fact_id])
    await storage.increment_query_hits([fact_id])

    # Auto-promote (mirrors what engine.query does internally)
    promoted = await storage.promote_fact(fact_id)
    assert promoted is True

    # TTL sweep fires past the original expiry — promoted fact must survive
    await storage.expire_ttl_facts(as_of=_future_iso(2))

    fact = await storage.get_fact_by_id(fact_id)
    assert fact["valid_until"] is None


# ── Promotion overrides expiry ──────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_promotion_overrides_ttl_expiry(engine: EngramEngine, storage: Storage):
    """After engine.promote(), the TTL sweep must not expire the fact."""
    result = await engine.commit(
        content="Scratchpad: retry backoff starts at 100 ms",
        scope="lifecycle",
        confidence=0.65,
        agent_id="agent-1",
        durability="ephemeral",
        ttl_days=1,
    )
    fact_id = result["fact_id"]

    await engine.promote(fact_id)

    # Confirm durability is now durable
    fact = await storage.get_fact_by_id(fact_id)
    assert fact["durability"] == "durable"

    # TTL sweep should not touch the promoted fact
    await storage.expire_ttl_facts(as_of=_future_iso(2))

    fact = await storage.get_fact_by_id(fact_id)
    assert fact["valid_until"] is None


# ── Protected / durable facts never expire ──────────────────────────


@pytest.mark.asyncio
async def test_durable_fact_survives_ttl_sweep(engine: EngramEngine, storage: Storage):
    """A durable fact with no TTL is untouched by the TTL sweep, even far in the future."""
    result = await engine.commit(
        content="The payments service enforces PCI-DSS level 1",
        scope="lifecycle",
        confidence=0.95,
        agent_id="agent-1",
        durability="durable",
    )
    fact_id = result["fact_id"]

    await storage.expire_ttl_facts(as_of=_future_iso(365))

    fact = await storage.get_fact_by_id(fact_id)
    assert fact["valid_until"] is None


@pytest.mark.asyncio
async def test_corroborated_fact_survives_ttl_sweep(engine: EngramEngine, storage: Storage):
    """A durable, corroborated fact is unaffected by the TTL sweep."""
    result = await engine.commit(
        content="Service mesh uses mTLS for all inter-service calls",
        scope="lifecycle",
        confidence=0.9,
        agent_id="agent-1",
        provenance="architecture/decision-007.md",
        durability="durable",
    )
    fact_id = result["fact_id"]

    await storage.increment_corroboration(fact_id)

    await storage.expire_ttl_facts(as_of=_future_iso(365))

    fact = await storage.get_fact_by_id(fact_id)
    assert fact["valid_until"] is None
