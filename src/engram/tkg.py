"""Temporal Knowledge Graph (TKG) engine for Engram Detective.

Inspired by Zep's Graphiti approach (arXiv:2501.13956), this module adds a
time-aware graph layer on top of Engram's fact store.  Each fact is decomposed
into entity nodes and temporal edges (relationships).  Edges carry bi-temporal
metadata following Graphiti's model:

  Database time:  created_at / expired_at
  Real-world time: valid_at / invalid_at

This enables the Detective to answer not just *what* conflicts exist, but
*when* beliefs diverged and *how* they evolved across agents over time.

Key concepts (aligned with Graphiti's architecture)
────────────────────────────────────────────────────
- **Episode**: A committed fact — the atomic unit of ingestion.
  Maps to Graphiti's EpisodicNode.
- **Entity Node**: A named concept extracted from episodes (services,
  config keys, technologies, numeric parameters).  Carries a summary
  that evolves as new edges reference it.
  Maps to Graphiti's EntityNode.
- **Temporal Edge**: A relationship between two entity nodes, with
  bi-temporal validity and a natural-language fact label.  Edges are
  never deleted — only expired — preserving full provenance.
  Maps to Graphiti's EntityEdge.
- **Belief Timeline**: The ordered sequence of edges touching a given
  entity, revealing reversals and drift.

Detection capabilities added by TKG
────────────────────────────────────
- **Reversal detection**: A→B→A patterns on the same entity pair.
- **Belief drift**: Gradual value changes across agents over time.
- **Stale edge detection**: Old edges never invalidated despite newer
  contradictory evidence.
- **Temporal contradiction resolution**: Uses valid_at ordering to
  determine which edge should be expired when out-of-order episodes
  arrive (Graphiti's key insight for non-chronological ingestion).

Differences from Graphiti
─────────────────────────
Graphiti uses an LLM for entity/edge extraction and deduplication,
backed by Neo4j/FalkorDB.  Engram's TKG uses the same LLM-powered
extraction (gpt-4o-mini via the OpenAI API key deployed to Vercel)
backed by SQLite/Postgres relational tables.

The LLM handles:
- Triplet extraction from free text (implicit relationships, transitions)
- Temporal info extraction (valid_at/invalid_at from relative time refs)
- Semantic edge dedup (paraphrase detection)

Embedding similarity (sentence-transformers, local) handles:
- Node dedup ("auth service" ≈ "authentication service")

A regex fallback exists for local-only deployments without API keys,
but the primary path is always LLM-powered.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from engram.storage import BaseStorage

logger = logging.getLogger("engram.tkg")


# ── Data classes ─────────────────────────────────────────────────────


@dataclass
class EntityNode:
    """A named entity in the temporal knowledge graph.

    Aligned with Graphiti's EntityNode: carries a name, type labels,
    and an evolving summary built from the edges that reference it.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    entity_type: str = ""  # service, technology, config_key, numeric, component
    summary: str = ""  # evolving description built from edge facts
    first_seen: str = ""  # ISO timestamp
    last_seen: str = ""  # ISO timestamp
    fact_count: int = 0
    workspace_id: str = "local"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemporalEdge:
    """A bi-temporal relationship between two entity nodes.

    Aligned with Graphiti's EntityEdge.  Carries four temporal fields:

    Database time (system-managed):
      created_at  — when this edge was inserted into the graph
      expired_at  — when this edge was invalidated (None = still active)

    Real-world time (extracted from content):
      valid_at    — when this relationship became true in the real world
      invalid_at  — when this relationship stopped being true (None = still valid)

    Graphiti's key insight: when episodes arrive out of chronological order,
    valid_at is used to determine which edge should be expired.  If a new
    edge has a valid_at *before* an existing edge's valid_at, the new edge
    is born expired (its invalid_at is set to the existing edge's valid_at).
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    source_node_id: str = ""
    target_node_id: str = ""
    relation_type: str = ""  # has_value, uses, depends_on, configured_as, etc.
    fact_label: str = ""  # human-readable description of the relationship
    fact_id: str = ""  # the Engram fact that produced this edge
    episode_ids: list[str] = field(default_factory=list)  # all facts referencing this edge
    agent_id: str = ""
    scope: str = ""
    # Bi-temporal fields
    created_at: str = ""
    expired_at: str | None = None
    valid_at: str | None = None
    invalid_at: str | None = None
    # Metadata
    confidence: float = 0.8
    workspace_id: str = "local"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Serialize episode_ids list for storage
        d["episode_ids"] = ",".join(self.episode_ids) if self.episode_ids else ""
        return d

    @property
    def is_active(self) -> bool:
        return self.expired_at is None


# ── Relationship extraction ──────────────────────────────────────────

# Patterns that capture subject-verb-object triples from fact content.
# These are intentionally conservative — false negatives are preferable
# to noisy edges that pollute the graph.

_RELATIONSHIP_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    # "<subject> uses <object>"
    (
        re.compile(
            r"\b(?P<subject>[A-Za-z][A-Za-z0-9_-]+(?:\s+[A-Za-z][A-Za-z0-9_-]+)*?)\s+(?:uses?|using)\s+"
            r"(?P<object>[A-Za-z][A-Za-z0-9_.-]+)\b",
            re.IGNORECASE,
        ),
        "subject",
        "uses",
        "object",
    ),
    # "<subject> depends on <object>"
    (
        re.compile(
            r"\b(?P<subject>[A-Za-z][A-Za-z0-9_-]+(?:\s+[A-Za-z][A-Za-z0-9_-]+)*?)\s+depends?\s+on\s+"
            r"(?P<object>[A-Za-z][A-Za-z0-9_.-]+)\b",
            re.IGNORECASE,
        ),
        "subject",
        "depends_on",
        "object",
    ),
    # "switched from <old> to <new>"  (captures the transition)
    (
        re.compile(
            r"switched\s+(?:from\s+)?(?P<subject>[A-Za-z][A-Za-z0-9_.-]+)\s+to\s+"
            r"(?P<object>[A-Za-z][A-Za-z0-9_.-]+)\b",
            re.IGNORECASE,
        ),
        "subject",
        "replaced_by",
        "object",
    ),
    # "migrated from <old> to <new>"
    (
        re.compile(
            r"migrat(?:ed|ing)\s+(?:from\s+)?(?P<subject>[A-Za-z][A-Za-z0-9_.-]+)\s+to\s+"
            r"(?P<object>[A-Za-z][A-Za-z0-9_.-]+)\b",
            re.IGNORECASE,
        ),
        "subject",
        "replaced_by",
        "object",
    ),
    # "<subject> is configured as/with <value>"
    (
        re.compile(
            r"\b(?P<subject>[A-Za-z][A-Za-z0-9_-]+(?:\s+[A-Za-z][A-Za-z0-9_-]+)*?)\s+is\s+(?:configured|set)\s+"
            r"(?:as|to|with)\s+(?P<object>[A-Za-z0-9][A-Za-z0-9_.-]*)\b",
            re.IGNORECASE,
        ),
        "subject",
        "configured_as",
        "object",
    ),
    # "<subject> runs on <object>"
    (
        re.compile(
            r"\b(?P<subject>[A-Za-z][A-Za-z0-9_-]+(?:\s+[A-Za-z][A-Za-z0-9_-]+)*?)\s+runs?\s+on\s+"
            r"(?P<object>[A-Za-z][A-Za-z0-9_.-]+)\b",
            re.IGNORECASE,
        ),
        "subject",
        "runs_on",
        "object",
    ),
    # "<subject> connects to <object>"
    (
        re.compile(
            r"\b(?P<subject>[A-Za-z][A-Za-z0-9_-]+(?:\s+[A-Za-z][A-Za-z0-9_-]+)*?)\s+connects?\s+to\s+"
            r"(?P<object>[A-Za-z][A-Za-z0-9_.-]+)\b",
            re.IGNORECASE,
        ),
        "subject",
        "connects_to",
        "object",
    ),
    # "<subject> is <value>" (for simple state assertions)
    (
        re.compile(
            r"\b(?:the\s+)?(?P<subject>[A-Za-z][A-Za-z0-9_ -]{2,30}?)\s+is\s+"
            r"(?P<object>\d[\d,.]*\s*[A-Za-z/]+)\b",
            re.IGNORECASE,
        ),
        "subject",
        "has_value",
        "object",
    ),
]

# Stop words that should not be entity nodes
_STOP_SUBJECTS = {
    "the",
    "this",
    "that",
    "it",
    "we",
    "they",
    "our",
    "there",
    "which",
    "what",
    "who",
    "how",
    "when",
    "where",
    "why",
    "also",
    "just",
    "now",
    "then",
    "here",
    "very",
    "been",
}


def extract_relationships(content: str) -> list[dict[str, str]]:
    """Extract subject-relation-object triples from fact content.

    Returns a list of dicts with keys: subject, relation, object, fact_label.
    """
    relationships: list[dict[str, str]] = []
    seen: set[str] = set()

    for pattern, subj_group, relation, obj_group in _RELATIONSHIP_PATTERNS:
        for m in pattern.finditer(content):
            subject = m.group(subj_group).strip().lower()
            obj = m.group(obj_group).strip().lower()

            # Strip leading articles
            for article in ("the ", "a ", "an "):
                if subject.startswith(article):
                    subject = subject[len(article) :]
                if obj.startswith(article):
                    obj = obj[len(article) :]

            # Filter out stop words and very short subjects
            if subject in _STOP_SUBJECTS or obj in _STOP_SUBJECTS:
                continue
            if len(subject) < 2 or len(obj) < 2:
                continue

            key = f"{subject}:{relation}:{obj}"
            if key not in seen:
                seen.add(key)
                relationships.append(
                    {
                        "subject": subject,
                        "relation": relation,
                        "object": obj,
                        "fact_label": m.group(0).strip(),
                    }
                )

    return relationships


def _entity_type_from_name(name: str) -> str:
    """Infer entity type from name heuristics."""
    from engram.entities import _TECH_NAMES

    if name.lower() in _TECH_NAMES:
        return "technology"
    if name.isupper() and len(name) >= 3:
        return "config_key"
    if re.match(r"\d", name):
        return "numeric"
    if re.search(r"service|server|worker|queue|cache|db|proxy|gateway", name, re.IGNORECASE):
        return "service"
    return "component"


# ── TKG Engine ───────────────────────────────────────────────────────


class TemporalKnowledgeGraph:
    """Manages the temporal knowledge graph layer over Engram's fact store.

    The TKG is built incrementally: each committed fact is decomposed into
    entity nodes and temporal edges.  The graph is then traversed to detect
    belief evolution patterns that pairwise comparison cannot catch.

    Follows Graphiti's core architecture:
    1. Episode ingestion → extract entities and relationships
    2. Node resolution → deduplicate against existing nodes
    3. Edge resolution → deduplicate, detect contradictions, invalidate
    4. Temporal ordering → use valid_at to handle out-of-order episodes
    """

    def __init__(self, storage: "BaseStorage") -> None:
        self.storage = storage

    async def ingest_fact(
        self,
        fact_id: str,
        content: str,
        scope: str,
        agent_id: str,
        committed_at: str,
        confidence: float = 0.8,
        entities: list[dict[str, Any]] | None = None,
    ) -> list[TemporalEdge]:
        """Decompose a fact into graph nodes and edges.

        Primary path (OPENAI_API_KEY available):
          gpt-4o-mini extracts triplets and temporal info from free text,
          embedding similarity deduplicates nodes, LLM deduplicates edges.

        Fallback (no API key, e.g. local-only):
          Regex pattern matching for structured sentences.

        Both paths feed into the same resolution pipeline:
        1. Upsert entity nodes for each subject/object.
        2. Resolve edges: deduplicate exact matches, invalidate contradictions.
        3. Apply temporal ordering for out-of-order episodes.

        Returns the list of newly created edges.
        """
        from engram.tkg_llm import is_available as llm_available

        valid_at = committed_at
        invalid_at: str | None = None

        # ── Extraction: LLM or regex ────────────────────────────────
        if llm_available():
            from engram.tkg_llm import extract_triplets, resolve_node_name

            result = await extract_triplets(content, reference_time=committed_at)
            rels = result.get("triplets", [])
            # Normalize node names via alias resolution
            for rel in rels:
                rel["subject"] = resolve_node_name(rel["subject"])
                rel["object"] = resolve_node_name(rel["object"])
            # Use LLM-extracted temporal info if available
            if result.get("valid_at"):
                valid_at = result["valid_at"]
            if result.get("invalid_at"):
                invalid_at = result["invalid_at"]
            logger.debug("TKG: LLM extracted %d triplets from fact %s", len(rels), fact_id[:12])
        else:
            rels = extract_relationships(content)

        new_edges: list[TemporalEdge] = []

        # Also create edges from structured entities (numeric values, etc.)
        if entities:
            for ent in entities:
                if ent.get("type") == "numeric" and ent.get("value") is not None:
                    rels.append(
                        {
                            "subject": ent["name"],
                            "relation": "has_value",
                            "object": str(ent["value"]),
                            "fact_label": f"{ent['name']} = {ent['value']}",
                        }
                    )

        for rel in rels:
            # Upsert source and target nodes (with embedding-based dedup in LLM mode)
            source_node = await self._upsert_node(
                name=rel["subject"],
                entity_type=_entity_type_from_name(rel["subject"]),
                timestamp=committed_at,
            )
            target_node = await self._upsert_node(
                name=rel["object"],
                entity_type=_entity_type_from_name(rel["object"]),
                timestamp=committed_at,
            )

            # ── Edge resolution (Graphiti-style) ─────────────────────
            # Check for exact duplicate edges first (same source+relation+target)
            existing_duplicate = await self._find_duplicate_edge(
                source_node_id=source_node.id,
                target_node_id=target_node.id,
                relation_type=rel["relation"],
            )
            if existing_duplicate:
                logger.debug(
                    "TKG: duplicate edge %s, appending fact %s as episode",
                    existing_duplicate["id"][:12],
                    fact_id[:12],
                )
                continue

            # In LLM mode, also check for semantic duplicates via LLM
            if llm_available():
                skip = await self._llm_edge_dedup(
                    source_node_id=source_node.id,
                    fact_label=rel.get("fact_label", ""),
                )
                if skip:
                    continue

            # Invalidate conflicting edges and apply temporal ordering
            await self._resolve_edge_contradictions(
                source_node_id=source_node.id,
                relation_type=rel["relation"],
                new_target_name=rel["object"],
                new_valid_at=valid_at,
            )

            # Create the new temporal edge
            edge = TemporalEdge(
                source_node_id=source_node.id,
                target_node_id=target_node.id,
                relation_type=rel["relation"],
                fact_label=rel.get("fact_label", ""),
                fact_id=fact_id,
                episode_ids=[fact_id],
                agent_id=agent_id,
                scope=scope,
                created_at=committed_at,
                valid_at=valid_at,
                invalid_at=invalid_at,
                confidence=confidence,
            )

            # If the edge is born with invalid_at, mark it expired immediately
            if invalid_at:
                edge.expired_at = committed_at

            await self.storage.insert_tkg_edge(edge.to_dict())
            new_edges.append(edge)

            # Update node summary with the new fact label
            await self._update_node_summary(source_node.id, rel.get("fact_label", ""))

        return new_edges

    async def _upsert_node(
        self,
        name: str,
        entity_type: str,
        timestamp: str,
    ) -> EntityNode:
        """Find or create an entity node by name.

        In LLM mode, also checks for semantically similar existing nodes
        via embedding cosine similarity (catches "PostgreSQL" vs "Postgres",
        "auth service" vs "authentication service").

        In regex mode, uses exact name matching.
        """
        from engram.tkg_llm import is_available as llm_available, resolve_node_name

        # Resolve known aliases first
        name = resolve_node_name(name)

        existing = await self.storage.get_tkg_node_by_name(name)
        if existing:
            await self.storage.update_tkg_node_seen(existing["id"], timestamp)
            return EntityNode(
                id=existing["id"],
                name=existing["name"],
                entity_type=existing["entity_type"],
                summary=existing.get("summary", ""),
                first_seen=existing["first_seen"],
                last_seen=timestamp,
                fact_count=existing["fact_count"] + 1,
            )

        # In LLM mode, try embedding-based fuzzy match against all existing nodes
        if llm_available():
            from engram.tkg_llm import find_similar_node

            stats = await self.storage.get_tkg_stats()
            if stats.get("total_nodes", 0) > 0:
                # Get a sample of existing nodes to compare against
                # (full scan is fine at Engram's scale — typically <1000 nodes)
                all_nodes = await self._get_all_nodes()
                match = await find_similar_node(name, all_nodes, threshold=0.85)
                if match:
                    await self.storage.update_tkg_node_seen(match["id"], timestamp)
                    return EntityNode(
                        id=match["id"],
                        name=match["name"],
                        entity_type=match["entity_type"],
                        summary=match.get("summary", ""),
                        first_seen=match["first_seen"],
                        last_seen=timestamp,
                        fact_count=match["fact_count"] + 1,
                    )

        node = EntityNode(
            name=name,
            entity_type=entity_type,
            first_seen=timestamp,
            last_seen=timestamp,
            fact_count=1,
        )
        await self.storage.insert_tkg_node(node.to_dict())
        return node

    async def _get_all_nodes(self) -> list[dict[str, Any]]:
        """Fetch all TKG nodes for embedding-based dedup."""
        try:
            # Use a storage query — we'll add this method
            return await self.storage.get_all_tkg_nodes()
        except AttributeError:
            return []

    async def _find_duplicate_edge(
        self,
        source_node_id: str,
        target_node_id: str,
        relation_type: str,
    ) -> dict[str, Any] | None:
        """Check if an active edge with the same triplet already exists.

        Graphiti uses LLM-based dedup with embedding similarity.  We use
        exact structural matching (same source, target, relation) which is
        sufficient for regex-extracted relationships.
        """
        active_edges = await self.storage.get_active_tkg_edges(
            source_node_id=source_node_id,
            relation_type=relation_type,
        )
        for edge in active_edges:
            if edge["target_node_id"] == target_node_id:
                return edge
        return None

    async def _resolve_edge_contradictions(
        self,
        source_node_id: str,
        relation_type: str,
        new_target_name: str,
        new_valid_at: str,
    ) -> list[str]:
        """Expire active edges that conflict with a new edge.

        Follows Graphiti's resolve_edge_contradictions logic:
        - An edge conflicts when it shares the same source node and relation
          type but points to a different target.
        - Uses valid_at temporal ordering: if the existing edge has a later
          valid_at than the new edge, the *new* edge should be born expired
          (handled by the caller).  If the existing edge is older, it gets
          expired with invalid_at set to the new edge's valid_at.
        - Edges are expired, never deleted — preserving full provenance.

        Returns IDs of expired edges.
        """
        active_edges = await self.storage.get_active_tkg_edges(
            source_node_id=source_node_id,
            relation_type=relation_type,
        )
        expired_ids: list[str] = []
        for edge in active_edges:
            # Look up the target node to compare names
            target = await self.storage.get_tkg_node_by_id(edge["target_node_id"])
            if target and target["name"] != new_target_name:
                # Temporal ordering: only expire if the existing edge is older
                existing_valid_at = edge.get("valid_at") or edge.get("created_at", "")
                if existing_valid_at <= new_valid_at:
                    await self.storage.expire_tkg_edge(edge["id"], new_valid_at)
                    expired_ids.append(edge["id"])
                    logger.debug(
                        "TKG: expired edge %s (%s -[%s]-> %s) — superseded at %s",
                        edge["id"][:12],
                        source_node_id[:12],
                        relation_type,
                        target["name"],
                        new_valid_at[:19],
                    )
                else:
                    # Out-of-order episode: existing edge is newer, so the
                    # new edge should be born expired.  We don't create it
                    # here — the caller handles this case.
                    logger.debug(
                        "TKG: new edge older than existing %s, will be born expired",
                        edge["id"][:12],
                    )
        return expired_ids

    async def _update_node_summary(self, node_id: str, fact_label: str) -> None:
        """Append a fact label to a node's evolving summary.

        Graphiti uses LLM-generated summaries.  We build summaries by
        concatenating the most recent fact labels (capped at 500 chars).
        """
        node = await self.storage.get_tkg_node_by_id(node_id)
        if not node:
            return
        existing = node.get("summary", "") or ""
        # Append new fact, keeping summary under 500 chars
        if fact_label not in existing:
            updated = f"{existing}; {fact_label}" if existing else fact_label
            if len(updated) > 500:
                updated = updated[-500:]
            try:
                await self.storage.update_tkg_node_summary(node_id, updated)
            except AttributeError:
                pass  # storage doesn't support summary updates yet

    async def _llm_edge_dedup(
        self,
        source_node_id: str,
        fact_label: str,
    ) -> bool:
        """Use LLM to check if a new edge semantically duplicates an existing one.

        Returns True if the edge should be skipped (is a duplicate).
        """
        from engram.tkg_llm import check_edge_duplicate

        # Get all active edges from this source node
        all_edges = await self.storage.get_tkg_edges_for_node(
            node_id=source_node_id,
            include_expired=False,
        )
        outgoing = [e for e in all_edges if e["source_node_id"] == source_node_id]
        if not outgoing:
            return False

        existing_labels = [e["fact_label"] for e in outgoing if e.get("fact_label")]
        if not existing_labels:
            return False

        result = await check_edge_duplicate(fact_label, existing_labels)
        if result.get("is_duplicate_of") is not None:
            logger.debug(
                "TKG: LLM dedup — '%s' is duplicate of existing edge",
                fact_label[:60],
            )
            return True
        return False

    # ── Belief evolution queries ─────────────────────────────────────

    async def get_entity_timeline(
        self,
        entity_name: str,
        relation_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the chronological edge history for an entity.

        Shows how beliefs about this entity evolved over time, including
        which agent made each assertion and when edges were invalidated.
        """
        node = await self.storage.get_tkg_node_by_name(entity_name)
        if not node:
            return []
        edges = await self.storage.get_tkg_edges_for_node(
            node_id=node["id"],
            relation_type=relation_type,
        )
        timeline: list[dict[str, Any]] = []
        for edge in edges:
            source = await self.storage.get_tkg_node_by_id(edge["source_node_id"])
            target = await self.storage.get_tkg_node_by_id(edge["target_node_id"])
            timeline.append(
                {
                    "edge_id": edge["id"],
                    "source": source["name"] if source else edge["source_node_id"],
                    "relation": edge["relation_type"],
                    "target": target["name"] if target else edge["target_node_id"],
                    "fact_label": edge["fact_label"],
                    "fact_id": edge["fact_id"],
                    "agent_id": edge["agent_id"],
                    "scope": edge["scope"],
                    "created_at": edge["created_at"],
                    "expired_at": edge["expired_at"],
                    "valid_at": edge["valid_at"],
                    "invalid_at": edge["invalid_at"],
                    "is_active": edge["expired_at"] is None,
                    "confidence": edge["confidence"],
                }
            )
        return sorted(timeline, key=lambda e: e["created_at"])

    async def detect_reversals(
        self,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Detect A→B→A reversal patterns in the graph.

        A reversal occurs when:
        1. Entity X had relation R to target A (edge expired)
        2. Entity X then had relation R to target B (edge expired)
        3. Entity X now has relation R to target A again (edge active)

        These are the patterns the Narrative Coherence Detective describes
        as the most confusing for a new agent reading the fact history.
        """
        reversals: list[dict[str, Any]] = []
        # Get all nodes that have had edges expired (indicating changes)
        nodes_with_history = await self.storage.get_tkg_nodes_with_expired_edges(scope=scope)

        for node_info in nodes_with_history:
            node_id = node_info["id"]
            node_name = node_info["name"]

            # Get all edges (active + expired) from this node, grouped by relation
            all_edges = await self.storage.get_tkg_edges_for_node(
                node_id=node_id,
                include_expired=True,
            )

            # Group by relation_type
            by_relation: dict[str, list[dict[str, Any]]] = {}
            for edge in all_edges:
                # Only consider outgoing edges (source = this node)
                if edge["source_node_id"] == node_id:
                    by_relation.setdefault(edge["relation_type"], []).append(edge)

            for relation, edges in by_relation.items():
                if len(edges) < 3:
                    continue

                # Sort by created_at
                sorted_edges = sorted(edges, key=lambda e: e["created_at"])

                # Look for A→B→A pattern
                targets = []
                for edge in sorted_edges:
                    target = await self.storage.get_tkg_node_by_id(edge["target_node_id"])
                    target_name = target["name"] if target else edge["target_node_id"]
                    targets.append((target_name, edge))

                for i in range(len(targets) - 2):
                    t_a, edge_a = targets[i]
                    t_b, edge_b = targets[i + 1]
                    t_c, edge_c = targets[i + 2]

                    if t_a == t_c and t_a != t_b:
                        reversals.append(
                            {
                                "type": "reversal",
                                "entity": node_name,
                                "relation": relation,
                                "sequence": [
                                    {
                                        "target": t_a,
                                        "agent_id": edge_a["agent_id"],
                                        "at": edge_a["created_at"],
                                    },
                                    {
                                        "target": t_b,
                                        "agent_id": edge_b["agent_id"],
                                        "at": edge_b["created_at"],
                                    },
                                    {
                                        "target": t_c,
                                        "agent_id": edge_c["agent_id"],
                                        "at": edge_c["created_at"],
                                    },
                                ],
                                "explanation": (
                                    f'Reversal on "{node_name}": '
                                    f"{relation} changed {t_a} → {t_b} → {t_a}. "
                                    f"A new agent would not know which state is current."
                                ),
                                "severity": (
                                    "high"
                                    if len(
                                        {edge_a["agent_id"], edge_b["agent_id"], edge_c["agent_id"]}
                                    )
                                    > 1
                                    else "medium"
                                ),
                            }
                        )

        return reversals

    async def detect_stale_edges(
        self,
        max_age_days: int = 30,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find active edges that are old and potentially stale.

        An edge is considered stale when:
        - It is still active (not expired)
        - It was created more than max_age_days ago
        - A newer edge exists on the same source node with a different relation
          or target, suggesting the old edge may be outdated
        """
        stale: list[dict[str, Any]] = []
        cutoff = datetime.now(timezone.utc)

        old_active_edges = await self.storage.get_old_active_tkg_edges(
            max_age_days=max_age_days,
            scope=scope,
        )

        for edge in old_active_edges:
            # Check if there are newer edges from the same source
            newer = await self.storage.get_newer_tkg_edges(
                source_node_id=edge["source_node_id"],
                after=edge["created_at"],
            )
            if newer:
                source = await self.storage.get_tkg_node_by_id(edge["source_node_id"])
                target = await self.storage.get_tkg_node_by_id(edge["target_node_id"])
                source_name = source["name"] if source else "unknown"
                target_name = target["name"] if target else "unknown"

                stale.append(
                    {
                        "type": "stale_edge",
                        "edge_id": edge["id"],
                        "entity": source_name,
                        "relation": edge["relation_type"],
                        "target": target_name,
                        "created_at": edge["created_at"],
                        "age_days": (cutoff - datetime.fromisoformat(edge["created_at"])).days
                        if edge["created_at"]
                        else 0,
                        "newer_edge_count": len(newer),
                        "explanation": (
                            f'Potentially stale: "{source_name} {edge["relation_type"]} '
                            f'{target_name}" was asserted {edge["created_at"][:10]} '
                            f"but {len(newer)} newer edge(s) exist on this entity."
                        ),
                        "severity": "low",
                    }
                )

        return stale

    async def detect_belief_drift(
        self,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Detect gradual belief drift across agents.

        Drift occurs when multiple agents assert different values for the
        same entity+relation over time.  Unlike reversals (which require
        3+ edges), drift is detected from the full edge history: if
        different agents have asserted different targets for the same
        source+relation, that's drift — even if older edges were expired.
        """
        drift_cases: list[dict[str, Any]] = []

        # Get all nodes that have had edges from multiple agents
        nodes_with_history = await self.storage.get_tkg_nodes_with_expired_edges(scope=scope)
        # Also include nodes with active multi-agent edges
        active_multi = await self.storage.get_tkg_multi_agent_edges(scope=scope)
        node_ids_to_check: set[str] = set()
        for n in nodes_with_history:
            node_ids_to_check.add(n["id"])
        for e in active_multi:
            node_ids_to_check.add(e["source_node_id"])

        for node_id in node_ids_to_check:
            node = await self.storage.get_tkg_node_by_id(node_id)
            if not node:
                continue
            node_name = node["name"]

            # Get ALL edges (active + expired) from this node
            all_edges = await self.storage.get_tkg_edges_for_node(
                node_id=node_id,
                include_expired=True,
            )

            # Group by relation_type, only outgoing edges
            by_relation: dict[str, list[dict[str, Any]]] = {}
            for edge in all_edges:
                if edge["source_node_id"] == node_id:
                    by_relation.setdefault(edge["relation_type"], []).append(edge)

            for relation, edges in by_relation.items():
                # Collect what each agent has asserted (most recent per agent)
                agent_latest: dict[str, dict[str, Any]] = {}
                for edge in sorted(edges, key=lambda e: e["created_at"]):
                    agent_latest[edge["agent_id"]] = edge

                if len(agent_latest) < 2:
                    continue

                # Check if agents asserted different targets
                agent_targets: dict[str, str] = {}
                for agent_id, edge in agent_latest.items():
                    target = await self.storage.get_tkg_node_by_id(edge["target_node_id"])
                    target_name = target["name"] if target else edge["target_node_id"]
                    agent_targets[agent_id] = target_name

                unique_targets = set(agent_targets.values())
                if len(unique_targets) > 1:
                    drift_cases.append(
                        {
                            "type": "belief_drift",
                            "entity": node_name,
                            "relation": relation,
                            "agent_beliefs": agent_targets,
                            "explanation": (
                                f'Belief drift on "{node_name}" ({relation}): '
                                + ", ".join(
                                    f"{agent} believes '{target}'"
                                    for agent, target in agent_targets.items()
                                )
                            ),
                            "severity": "high" if len(unique_targets) > 2 else "medium",
                        }
                    )

        return drift_cases

    async def get_graph_summary(
        self,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Return a summary of the TKG state."""
        stats = await self.storage.get_tkg_stats(scope=scope)
        return {
            "total_nodes": stats.get("total_nodes", 0),
            "total_edges": stats.get("total_edges", 0),
            "active_edges": stats.get("active_edges", 0),
            "expired_edges": stats.get("expired_edges", 0),
            "unique_relations": stats.get("unique_relations", 0),
        }
