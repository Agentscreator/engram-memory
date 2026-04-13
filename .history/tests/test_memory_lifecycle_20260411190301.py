"""Lifecycle tests for ephemeral memory: TTL expiry, reinforcement, promotion, durability.

These tests validate the README claims:
  - Ephemeral facts expire after TTL
  - Reinforcement (auto-promotion via query hits) prevents expiry
  - Explicit promotion clears TTL and overrides expiry
  - Durable facts are never swept by the TTL worker

Design note on time control
---------------------------
The engine pre-sets ``valid_until`` at commit time for facts with ``ttl_days``.
The ``expire_ttl_facts`` sweep targets storage-level facts that have ``ttl_days``
but no ``valid_until`` (e.g. low-level inserts).  Passing ``as_of`` to
``expire_ttl_facts`` simulates the sweep running in the future without any
real sleep — deterministic, instant, no wall-clock dependency.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from engram.engine import EngramEngine
from engram.storage import Storage


def _future_iso(days: int) -> str:
    """Return an ISO timestamp ``days`` into the future."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past_iso(days: int) -> str:
    """Return an ISO timestamp ``days`` in the past."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _ephemeral_fact(*, ttl_days: int) -> dict:
    """Build a minimal ephemeral fact dict for direct storage insertion.

    ``valid_from`` is set to the past so the TTL has already elapsed by
    the time ``expire_ttl_facts`` is called with the current time.
    """
    past = _past_iso(ttl_days + 1)
    return {
        "id": uuid.uuid4().hex,
        "lineage_id": uuid.uuid4().hex,
        "content": "Scratchpad: test fact for TTL sweep",
        "content_hash": uuid.uuid4().hex,
        "scope": "lifecycle",
        "confidence": 0.6,
        "fact_type": "observation",
        "agent_id": "agent-1",
        "embedding_model": "test",
        "embedding_ver": "0",
        "committed_at": past,
        "valid_from": past,
        "valid_until": None,
        "ttl_days": ttl_days,
        "durability": "ephemeral",
    }


# ── Ephemeral expiry ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ephemeral_fact_is_immediately_retrievable(engine: EngramEngine, storage: Storage):
    """An ephemeral fact exists in storage right after commit.

    The engine applies a 1-day default TTL to all ephemeral facts, so
    ``valid_until`` is set to a future timestamp — not NULL.  The important
    invariant is that the fact exists and hasn't expired yet.
    """
    result = await engine.commit(
        content="Scratchpad: auth warm-up takes 3 seconds",
        scope="lifecycle",
        confidence=0.6,
        agent_id="agent-1",
        durability="ephemeral",
    )
    fact = await storage.get_fact_by_id(result["fact_id"])
    assert fact is not None
    assert fact["durability"] == "ephemeral"
    # Engine pre-sets valid_until to a future date (default 1-day TTL for ephemeral)
    assert fact["valid_until"] is not None
    expiry = datetime.fromisoformat(fact["valid_until"])
    assert expiry > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_ephemeral_fact_expires_after_ttl_sweep(storage: Storage):
    """A directly-inserted ephemeral fact with elapsed TTL is closed by the TTL sweep."""
    fact = _ephemeral_fact(ttl_days=1)
    await storage.insert_fact(fact)

    row = await storage.get_fact_by_id(fact["id"])
    assert row["valid_until"] is None  # not yet swept

    # Simulate sweep running 2 days from now
    expired = await storage.expire_ttl_facts(as_of=_future_iso(2))
    assert expired >= 1

    row = await storage.get_fact_by_id(fact["id"])
    assert row["valid_until"] is not None


# ── Reinforcement prevents expiry ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reinforcement_marks_fact_as_promotable(storage: Storage):
    """After two query hits, a no-TTL ephemeral fact is eligible for auto-promotion.

    The promotable query requires ``valid_until IS NULL``.  Since the engine
    always sets a default 1-day TTL for ephemeral facts, this test uses a
    direct storage insert (valid_until=NULL) to exercise the promotion path.
    """
    fact = _ephemeral_fact(ttl_days=1)
    # Clear valid_until to simulate the no-TTL ephemeral scenario
    fact["valid_until"] = None
    fact["ttl_days"] = None
    await storage.insert_fact(fact)
    fact_id = fact["id"]

    await storage.increment_query_hits([fact_id])
    await storage.increment_query_hits([fact_id])

    promotable = await storage.get_promotable_ephemeral_facts(min_hits=2)
    assert any(p["id"] == fact_id for p in promotable)


@pytest.mark.asyncio
async def test_reinforcement_auto_promote_prevents_expiry(storage: Storage):
    """An ephemeral fact promoted after reaching the query-hit threshold survives the TTL sweep."""
    fact = _ephemeral_fact(ttl_days=1)
    await storage.insert_fact(fact)
    fact_id = fact["id"]

    # Simulate two query hits + auto-promotion (mirrors what engine.query does)
    await storage.increment_query_hits([fact_id])
    await storage.increment_query_hits([fact_id])
    promoted = await storage.promote_fact(fact_id)
    assert promoted is True

    # TTL sweep fires past the original expiry — promoted (durable) fact must survive
    swept = await storage.expire_ttl_facts(as_of=_future_iso(2))
    assert swept == 0  # only ephemeral facts are eligible; this one is now durable

    row = await storage.get_fact_by_id(fact_id)
    assert row["valid_until"] is None
    assert row["durability"] == "durable"


# ── Promotion overrides expiry ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_promotion_clears_ttl(engine: EngramEngine, storage: Storage):
    """engine.promote() clears valid_until and ttl_days — fact becomes permanently durable."""
    result = await engine.commit(
        content="Scratchpad: retry backoff starts at 100 ms",
        scope="lifecycle",
        confidence=0.65,
        agent_id="agent-1",
        durability="ephemeral",
        ttl_days=1,
    )
    fact_id = result["fact_id"]

    # Before promotion: engine pre-sets valid_until for TTL facts
    before = await storage.get_fact_by_id(fact_id)
    assert before["valid_until"] is not None
    assert before["ttl_days"] == 1

    await engine.promote(fact_id)

    after = await storage.get_fact_by_id(fact_id)
    assert after["durability"] == "durable"
    assert after["valid_until"] is None  # TTL cleared by promote
    assert after["ttl_days"] is None     # TTL cleared by promote


@pytest.mark.asyncio
async def test_explicit_promotion_overrides_ttl_sweep(storage: Storage):
    """A directly-inserted ephemeral fact that is promoted is not swept by expire_ttl_facts."""
    fact = _ephemeral_fact(ttl_days=1)
    await storage.insert_fact(fact)
    fact_id = fact["id"]

    promoted = await storage.promote_fact(fact_id)
    assert promoted is True

    swept = await storage.expire_ttl_facts(as_of=_future_iso(2))
    assert swept == 0  # promoted fact is durable; TTL sweep skips it

    row = await storage.get_fact_by_id(fact_id)
    assert row["valid_until"] is None


# ── Protected / durable facts never expire ───────────────────────────────────


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
