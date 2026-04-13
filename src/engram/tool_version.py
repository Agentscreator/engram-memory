"""MCP tool-surface versioning and deprecation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TOOL_SURFACE_VERSION = "1.0.0"
SUPPORTED_TOOL_MAJOR_VERSIONS = [1]

DEPRECATION_LIFECYCLE = {
    "announce": "Document the upcoming change in CHANGELOG.md.",
    "warn": "Accept the deprecated parameter and return a deprecation warning.",
    "remove": "Remove only in the next unsupported major version.",
}

DEPRECATION_POLICY = {
    "lifecycle": ["announce", "warn", "remove"],
    "compatibility": "current_major_and_previous_major_when_available",
}


@dataclass(frozen=True)
class DeprecatedParameter:
    tool: str
    old_name: str
    new_name: str
    deprecated_in: str
    remove_in: str
    guide: str


DEPRECATED_PARAMETERS: dict[tuple[str, str], DeprecatedParameter] = {
    ("engram_resolve", "winning_fact_id"): DeprecatedParameter(
        tool="engram_resolve",
        old_name="winning_fact_id",
        new_name="winning_claim_id",
        deprecated_in="1.0.0",
        remove_in="2.0.0",
        guide="CHANGELOG.md#tool-surface-migrations",
    ),
}


def tool_surface_metadata() -> dict[str, Any]:
    return {
        "tool_surface_version": TOOL_SURFACE_VERSION,
        "supported_tool_major_versions": SUPPORTED_TOOL_MAJOR_VERSIONS,
        "deprecation_policy": DEPRECATION_POLICY,
    }


def deprecation_warning(tool: str, old_name: str) -> dict[str, str] | None:
    item = DEPRECATED_PARAMETERS.get((tool, old_name))
    if item is None:
        return None
    return {
        "tool": item.tool,
        "parameter": item.old_name,
        "replacement": item.new_name,
        "deprecated_in": item.deprecated_in,
        "remove_in": item.remove_in,
        "guide": item.guide,
    }
