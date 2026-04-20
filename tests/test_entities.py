"""Tests for entity extraction."""

from engram.entities import extract_entities, extract_keywords


def test_extracts_numeric_with_unit():
    entities = extract_entities("The auth service rate-limits to 1000 req/s per IP")
    numerics = [e for e in entities if e["type"] == "numeric"]
    assert len(numerics) >= 1
    assert any(e["value"] == 1000 for e in numerics)


def test_extracts_config_key():
    entities = extract_entities("configured via AUTH_RATE_LIMIT in .env")
    config_keys = [e for e in entities if e["type"] == "config_key"]
    assert any(e["name"] == "AUTH_RATE_LIMIT" for e in config_keys)


def test_extracts_service_name():
    entities = extract_entities("the auth service handles JWT refresh")
    services = [e for e in entities if e["type"] == "service"]
    assert any(e["name"] == "auth" for e in services)


def test_extracts_technology():
    entities = extract_entities("We use PostgreSQL 15.2 for the main database")
    techs = [e for e in entities if e["type"] == "technology"]
    assert any(e["name"] == "postgresql" for e in techs)


def test_extracts_version():
    entities = extract_entities("Running Redis version 7.2.4")
    versions = [e for e in entities if e["type"] == "version"]
    assert any(e["value"] == "7.2.4" for e in versions)


def test_extracts_port():
    entities = extract_entities("PostgreSQL runs on port 5432")
    numerics = [e for e in entities if e["type"] == "numeric"]
    assert any(e["value"] == 5432 for e in numerics)


def test_keywords_extraction():
    keywords = extract_keywords("The auth service rate-limits to 1000 req/s per IP")
    assert "auth" in keywords
    assert "service" in keywords


def test_empty_content():
    assert extract_entities("") == []
    assert extract_keywords("") == []


def test_extracts_limit_value_from_maximum_phrase():
    entities = extract_entities(
        "The Free tier has a maximum of 3 projects. This limit MUST be enforced."
    )
    limit_entities = [e for e in entities if e.get("name") == "project_limit"]
    assert len(limit_entities) == 1
    assert limit_entities[0]["type"] == "numeric"
    assert limit_entities[0]["value"] == 3


def test_extracts_unlimited_as_sentinel():
    entities = extract_entities("Free tier = unlimited projects")
    limit_entities = [e for e in entities if e.get("name") == "project_limit"]
    assert len(limit_entities) == 1
    assert limit_entities[0]["type"] == "numeric"
    assert limit_entities[0]["value"] == -1


def test_unlimited_and_finite_limit_have_matching_names():
    """Tier 2 detection requires both facts to share the same entity name."""
    fact_a = extract_entities("Free tier = unlimited projects")
    fact_b = extract_entities(
        "The Free tier has a maximum of 3 projects. This limit MUST be enforced."
    )
    names_a = {e["name"] for e in fact_a if e["type"] == "numeric"}
    names_b = {e["name"] for e in fact_b if e["type"] == "numeric"}
    # They must share at least one name so Tier 2 can flag the conflict.
    assert names_a & names_b, f"No shared numeric entity names: {names_a} vs {names_b}"


def test_extracts_up_to_limit():
    entities = extract_entities("Free accounts can store up to 5 workspaces.")
    limit_entities = [e for e in entities if e.get("name") == "workspace_limit"]
    assert len(limit_entities) == 1
    assert limit_entities[0]["value"] == 5


def test_extracts_user_limit():
    entities = extract_entities("The plan allows a maximum of 10 users.")
    limit_entities = [e for e in entities if e.get("name") == "user_limit"]
    assert len(limit_entities) == 1
    assert limit_entities[0]["value"] == 10


def test_extracts_ticket_references():
    entities = extract_entities(
        "See GH-123, LINEAR-456, and JIRA-789 before changing the auth gateway."
    )
    ticket_entities = [e for e in entities if e["type"] == "ticket_ref"]
    assert {e["name"] for e in ticket_entities} == {"GH-123", "LINEAR-456", "JIRA-789"}
    assert {e["system"] for e in ticket_entities} == {"gh", "linear", "jira"}


def test_deduplicates_ticket_references():
    entities = extract_entities("GH-123 was discussed in GH-123 during rollout.")
    ticket_entities = [e for e in entities if e["type"] == "ticket_ref"]
    assert len(ticket_entities) == 1
    assert ticket_entities[0]["name"] == "GH-123"
