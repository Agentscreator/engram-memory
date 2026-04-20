"""Entity extraction — hybrid regex pipeline.

Extracts structured entities from fact content for Tier 0/2 detection.
Regex pass only for v0.1 (NER model is a future addition).
"""

from __future__ import annotations

import re
from typing import Any

# ── Regex patterns for entity extraction ─────────────────────────────

# Numeric values with units
_NUMERIC_PATTERNS = [
    # "1000 req/s", "500ms", "30 seconds", "5GB"
    re.compile(
        r"(?P<value>\d[\d,]*\.?\d*)\s*(?P<unit>req/s|rps|ms|seconds?|secs?|minutes?|mins?"
        r"|hours?|hrs?|days?|[KMGT]B|bytes?|%|connections?|threads?|workers?|retries|attempts)",
        re.IGNORECASE,
    ),
    # "port 5432", "version 3.2.1"
    re.compile(r"(?:port|version|v)\s*(?P<value>[\d.]+)", re.IGNORECASE),
]

# Limit/cap expressions: "maximum of 3 projects", "up to 5 users", "limit of 10 items"
# Captures the count and the limited concept so they get a stable name via _infer_limit_name.
_LIMIT_VALUE_PATTERN = re.compile(
    r"(?:maximum\s+of|max\s+of|up\s+to|at\s+most|cap\s+of|limit\s+of|"
    r"no\s+more\s+than|capped\s+at|limited\s+to)\s+"
    r"(?P<value>\d[\d,]*)\s+(?P<concept>[a-z][a-z0-9_-]*(?:\s+[a-z][a-z0-9_-]*)?)",
    re.IGNORECASE,
)

# Also: "3 project cap", "5 user limit" (count precedes the concept+limit noun)
_TRAILING_LIMIT_PATTERN = re.compile(
    r"(?P<value>\d[\d,]*)\s+(?P<concept>[a-z][a-z0-9_-]*(?:\s+[a-z][a-z0-9_-]*)?)"
    r"\s+(?:cap|limit|max|maximum|ceiling)",
    re.IGNORECASE,
)

# Unlimited / no-limit expressions — value sentinel is -1 (means "no finite cap").
# "unlimited projects", "no project limit", "removed the 3-project cap"
_UNLIMITED_PATTERN = re.compile(
    r"\bunlimited\s+(?P<concept>[a-z][a-z0-9_-]*(?:\s+[a-z][a-z0-9_-]*)?)",
    re.IGNORECASE,
)
_NO_LIMIT_PATTERN = re.compile(
    r"\bno\s+(?:(?P<concept1>[a-z][a-z0-9_-]*)\s+)?(?:limit|cap|ceiling|maximum|max)\b"
    r"(?:\s+on\s+(?P<concept2>[a-z][a-z0-9_-]*))?",
    re.IGNORECASE,
)

# ALL_CAPS identifiers (config keys, env vars)
_CONFIG_KEY_PATTERN = re.compile(r"\b(?P<name>[A-Z][A-Z0-9_]{2,})\b")

# Service/component names — heuristic: lowercase words before "service", "server", etc.
_SERVICE_PATTERN = re.compile(
    r"\b(?P<name>[a-z][a-z0-9_-]+)\s+(?:service|server|worker|queue|cache|database|db|proxy|gateway)\b",
    re.IGNORECASE,
)

# Version strings
_VERSION_PATTERN = re.compile(r"\bv?(?P<value>\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9.]+)?)\b")

# Ticket references: GH-123, LINEAR-456, JIRA-789
_TICKET_REF_PATTERN = re.compile(
    r"\b(?P<system>GH|LINEAR|JIRA)-(?P<id>\d+)\b",
    re.IGNORECASE,
)

# Technology names (common ones)
_TECH_NAMES = {
    "postgresql",
    "postgres",
    "mysql",
    "sqlite",
    "mongodb",
    "redis",
    "elasticsearch",
    "kafka",
    "rabbitmq",
    "nginx",
    "docker",
    "kubernetes",
    "k8s",
    "graphql",
    "grpc",
    "rest",
    "jwt",
    "oauth",
    "s3",
    "sqs",
    "sns",
    "dynamodb",
    "cloudfront",
    "lambda",
    "ecs",
    "eks",
    "rds",
}


def extract_entities(content: str) -> list[dict[str, Any]]:
    """Extract structured entities from fact content via regex.

    Returns a list of entity dicts: {name, type, value?, unit?}
    """
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Numeric values with units
    for pattern in _NUMERIC_PATTERNS:
        for m in pattern.finditer(content):
            value = m.group("value").replace(",", "")
            unit = m.group("unit") if "unit" in m.groupdict() else None
            # Try to find what this number describes from surrounding context
            start = max(0, m.start() - 60)
            context = content[start : m.start()].lower()
            name = _infer_numeric_name(context, unit)
            key = f"numeric:{name}:{value}"
            if key not in seen:
                seen.add(key)
                entity: dict[str, Any] = {
                    "name": name,
                    "type": "numeric",
                    "value": _parse_number(value),
                }
                if unit:
                    entity["unit"] = unit.lower()
                entities.append(entity)

    # Config keys (ALL_CAPS)
    for m in _CONFIG_KEY_PATTERN.finditer(content):
        name = m.group("name")
        # Skip very short or common English words that happen to be caps
        if len(name) < 3 or name in {"THE", "AND", "FOR", "NOT", "BUT", "ALL", "HAS", "WAS"}:
            continue
        key = f"config_key:{name}"
        if key not in seen:
            seen.add(key)
            entities.append({"name": name, "type": "config_key"})

    # Service names
    for m in _SERVICE_PATTERN.finditer(content):
        name = m.group("name").lower()
        key = f"service:{name}"
        if key not in seen:
            seen.add(key)
            entities.append({"name": name, "type": "service"})

    # Technology names
    content_lower = content.lower()
    for tech in _TECH_NAMES:
        if tech in content_lower:
            key = f"technology:{tech}"
            if key not in seen:
                seen.add(key)
                entities.append({"name": tech, "type": "technology"})

    # Version strings (only if not already captured as numeric)
    for m in _VERSION_PATTERN.finditer(content):
        value = m.group("value")
        start = max(0, m.start() - 40)
        context = content[start : m.start()].lower()
        name = _infer_version_name(context)
        key = f"version:{name}:{value}"
        if key not in seen:
            seen.add(key)
            entities.append({"name": name, "type": "version", "value": value})

    # Ticket references
    for m in _TICKET_REF_PATTERN.finditer(content):
        system = m.group("system").upper()
        ticket_id = m.group("id")
        ref = f"{system}-{ticket_id}"
        key = f"ticket_ref:{ref}"
        if key not in seen:
            seen.add(key)
            entities.append(
                {
                    "name": ref,
                    "type": "ticket_ref",
                    "value": ticket_id,
                    "system": system.lower(),
                }
            )

    # Limit/cap values: "maximum of 3 projects", "up to 5 users", etc.
    for pattern in (_LIMIT_VALUE_PATTERN, _TRAILING_LIMIT_PATTERN):
        for m in pattern.finditer(content):
            raw_value = m.group("value").replace(",", "")
            concept = m.group("concept").lower().strip()
            name = _infer_limit_name(concept)
            numeric_value = _parse_number(raw_value)
            key = f"numeric:{name}:{numeric_value}"
            if key not in seen:
                seen.add(key)
                entities.append({"name": name, "type": "numeric", "value": numeric_value})

    # Unlimited / no-limit expressions — sentinel value -1 means "no finite cap".
    for m in _UNLIMITED_PATTERN.finditer(content):
        concept = m.group("concept").lower().strip()
        name = _infer_limit_name(concept)
        key = f"numeric:{name}:-1"
        if key not in seen:
            seen.add(key)
            entities.append({"name": name, "type": "numeric", "value": -1})

    for m in _NO_LIMIT_PATTERN.finditer(content):
        concept = (m.group("concept1") or m.group("concept2") or "").lower().strip()
        if not concept:
            continue
        name = _infer_limit_name(concept)
        key = f"numeric:{name}:-1"
        if key not in seen:
            seen.add(key)
            entities.append({"name": name, "type": "numeric", "value": -1})

    return entities


def extract_keywords(content: str) -> list[str]:
    """Extract simple keywords from content for FTS enrichment."""
    # Remove common stop words and extract meaningful terms
    words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_-]{2,}\b", content)
    stop = {
        "the",
        "and",
        "for",
        "not",
        "but",
        "all",
        "has",
        "was",
        "are",
        "this",
        "that",
        "with",
        "from",
        "will",
        "been",
        "have",
        "does",
        "when",
        "which",
        "their",
        "about",
        "into",
        "than",
        "them",
        "then",
        "each",
        "other",
        "using",
        "used",
        "uses",
    }
    seen: set[str] = set()
    keywords: list[str] = []
    for w in words:
        wl = w.lower()
        if wl not in stop and wl not in seen:
            seen.add(wl)
            keywords.append(wl)
    return keywords[:30]  # Cap at 30 keywords


def _infer_limit_name(concept: str) -> str:
    """Map a concept noun phrase to a canonical limit-entity name.

    Called when extracting "maximum of N <concept>" or "unlimited <concept>".
    Returns a stable name so Tier 2 can compare the two entities.
    """
    concept = concept.lower().strip()
    mappings = [
        (r"projects?", "project_limit"),
        (r"users?|members?|accounts?", "user_limit"),
        (r"items?|records?|entries|rows?", "item_limit"),
        (r"seats?", "seat_limit"),
        (r"workspaces?", "workspace_limit"),
        (r"teams?", "team_limit"),
        (r"agents?", "agent_limit"),
        (r"requests?", "request_limit"),
        (r"api\s+calls?", "api_call_limit"),
        (r"connections?", "connection_limit"),
        (r"tasks?", "task_limit"),
        (r"files?|uploads?", "file_limit"),
        (r"storage", "storage_limit"),
    ]
    for pattern, name in mappings:
        if re.search(pattern, concept):
            return name
    # Fallback: normalise the concept phrase into a snake_case name
    slug = re.sub(r"\s+", "_", concept.strip())
    return f"{slug}_limit"


def _infer_numeric_name(context: str, unit: str | None) -> str:
    """Try to infer what a numeric value describes from surrounding text."""
    # Look for common patterns
    patterns = [
        (r"rate[- ]?limit", "rate_limit"),
        (r"timeout", "timeout"),
        (r"max[- ]?connections?", "max_connections"),
        (r"max[- ]?retries", "max_retries"),
        (r"ttl", "ttl"),
        (r"pool[- ]?size", "pool_size"),
        (r"batch[- ]?size", "batch_size"),
        (r"buffer[- ]?size", "buffer_size"),
        (r"cache[- ]?size", "cache_size"),
        (r"queue[- ]?size", "queue_size"),
        (r"threshold", "threshold"),
        (r"interval", "interval"),
        (r"port", "port"),
        (r"replicas?", "replicas"),
        (r"workers?", "workers"),
        (r"threads?", "threads"),
        (r"memory", "memory"),
        (r"cpu", "cpu"),
        (r"latency", "latency"),
        (r"throughput", "throughput"),
    ]
    for pattern, name in patterns:
        if re.search(pattern, context):
            return name
    if unit:
        return f"value_{unit.lower()}"
    return "numeric_value"


def _infer_version_name(context: str) -> str:
    """Try to infer what software a version string refers to."""
    # Check for technology names in context
    for tech in _TECH_NAMES:
        if tech in context:
            return f"{tech}_version"
    # Check for common patterns
    words = context.split()
    if words:
        return f"{words[-1].strip('.,:;')}_version"
    return "version"


def _parse_number(s: str) -> int | float:
    """Parse a numeric string to int or float."""
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return 0
