"""OpenAI Agents SDK integration for Engram."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from engram.client import EngramClient

try:
    from agents import function_tool as _function_tool
except ImportError as exc:  # pragma: no cover - exercised through helper tests
    _function_tool = None
    _OPENAI_AGENTS_IMPORT_ERROR = exc
else:
    _OPENAI_AGENTS_IMPORT_ERROR = None


ToolDecorator = Callable[[Callable[..., Any]], Any]


def _missing_openai_agents_error() -> ImportError:
    return ImportError(
        "OpenAI Agents SDK support is optional. Install it to use "
        "engram.integrations.openai_agents. Example: pip install openai-agents"
    )


def create_engram_tools(
    *,
    client: EngramClient | None = None,
    base_url: str = "http://127.0.0.1:7474",
    api_key: str | None = None,
    timeout: float = 30.0,
    default_scope: str | None = None,
    tool_decorator: ToolDecorator | None = None,
) -> list[Any]:
    """Create OpenAI Agents SDK function tools backed by Engram.

    The OpenAI Agents SDK remains optional. Pass ``tool_decorator`` in tests or
    advanced integrations to avoid importing the SDK directly.
    """
    decorator = tool_decorator or _function_tool
    if decorator is None:
        raise _missing_openai_agents_error() from _OPENAI_AGENTS_IMPORT_ERROR

    resolved_client = client or EngramClient(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
    )

    def engram_query(
        topic: str,
        scope: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Query verified Engram workspace facts relevant to a topic."""
        return resolved_client.query(
            topic,
            scope=scope or default_scope,
            limit=limit,
        )

    def engram_commit(
        content: str,
        scope: str | None = None,
        confidence: float = 0.8,
        fact_type: str = "observation",
        provenance: str | None = None,
    ) -> dict[str, Any]:
        """Commit a verified fact to Engram; do not store raw chat history."""
        return resolved_client.commit(
            content,
            scope=scope or default_scope or "general",
            confidence=confidence,
            fact_type=fact_type,
            provenance=provenance,
        )

    def engram_conflicts(
        scope: str | None = None,
        status: str = "open",
    ) -> list[dict[str, Any]]:
        """List Engram conflicts for review before important decisions."""
        return resolved_client.conflicts(
            scope=scope or default_scope,
            status=status,
        )

    return [
        decorator(engram_query),
        decorator(engram_commit),
        decorator(engram_conflicts),
    ]
