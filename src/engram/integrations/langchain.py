"""LangChain memory adapter for Engram."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from engram.client import EngramClient

try:
    from langchain_core.memory import BaseMemory
except ImportError as exc:  # pragma: no cover - exercised through helper tests
    BaseMemory = object  # type: ignore[assignment,misc]
    _LANGCHAIN_IMPORT_ERROR = exc
else:
    _LANGCHAIN_IMPORT_ERROR = None


LANGCHAIN_BASE_MEMORY_AVAILABLE = _LANGCHAIN_IMPORT_ERROR is None


class EngramMemory(BaseMemory):  # type: ignore[misc]
    """LangChain-compatible memory backed by Engram's REST API.

    The adapter uses LangChain's memory method names and subclasses
    ``BaseMemory`` when the installed LangChain version still provides it.
    Recent LangChain releases no longer expose that class, so this remains a
    lightweight compatible adapter instead of forcing a legacy dependency.

    It does not automatically write chain transcripts back to Engram; use
    ``commit_fact`` for verified facts.
    """

    if LANGCHAIN_BASE_MEMORY_AVAILABLE:
        model_config = ConfigDict(arbitrary_types_allowed=True)

        client: EngramClient = Field(default_factory=EngramClient)
        scope: str | None = None
        memory_key: str = "engram_memory"
        input_key: str = "input"
        limit: int = 5
        empty_message: str = "No Engram memory found."

    def __init__(
        self,
        *,
        client: EngramClient | None = None,
        base_url: str = "http://127.0.0.1:7474",
        api_key: str | None = None,
        timeout: float = 30.0,
        scope: str | None = None,
        memory_key: str = "engram_memory",
        input_key: str = "input",
        limit: int = 5,
        empty_message: str = "No Engram memory found.",
    ) -> None:
        resolved_client = client or EngramClient(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        if LANGCHAIN_BASE_MEMORY_AVAILABLE:
            super().__init__(
                client=resolved_client,
                scope=scope,
                memory_key=memory_key,
                input_key=input_key,
                limit=limit,
                empty_message=empty_message,
            )
            return
        self.client = resolved_client
        self.scope = scope
        self.memory_key = memory_key
        self.input_key = input_key
        self.limit = limit
        self.empty_message = empty_message

    @property
    def memory_variables(self) -> list[str]:
        return [self.memory_key]

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, str]:
        topic = self._topic_from_inputs(inputs)
        if not topic:
            return {self.memory_key: self.empty_message}
        facts = self.client.query(topic, scope=self.scope, limit=self.limit)
        return {self.memory_key: format_facts(facts, empty_message=self.empty_message)}

    async def aload_memory_variables(self, inputs: dict[str, Any]) -> dict[str, str]:
        return self.load_memory_variables(inputs)

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        """No-op by default to avoid committing unverified chat history."""
        return None

    async def asave_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        return None

    def clear(self) -> None:
        """No local state is stored by the adapter."""
        return None

    async def aclear(self) -> None:
        return None

    def commit_fact(
        self,
        content: str,
        *,
        scope: str | None = None,
        confidence: float = 0.8,
        fact_type: str = "observation",
        provenance: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Explicitly commit a verified fact to Engram."""
        return self.client.commit(
            content,
            scope=scope or self.scope or "general",
            confidence=confidence,
            fact_type=fact_type,
            provenance=provenance,
            agent_id=agent_id,
        )

    def _topic_from_inputs(self, inputs: dict[str, Any]) -> str:
        if self.input_key in inputs:
            return str(inputs[self.input_key])
        if len(inputs) == 1:
            return str(next(iter(inputs.values())))
        return ""


def format_facts(
    facts: list[dict[str, Any]], *, empty_message: str = "No Engram memory found."
) -> str:
    """Format Engram query results for prompt injection into a chain."""
    if not facts:
        return empty_message
    lines = []
    for fact in facts:
        content = fact.get("content") or ""
        scope = fact.get("scope") or "general"
        confidence = fact.get("effective_confidence", fact.get("confidence"))
        if confidence is None:
            lines.append(f"- [{scope}] {content}")
        else:
            lines.append(f"- [{scope}] {content} (confidence: {float(confidence):.2f})")
    return "\n".join(lines)
