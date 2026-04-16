"""Small REST client for Engram's HTTP API."""

from __future__ import annotations

import json
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


class EngramClientError(RuntimeError):
    """Raised when the Engram REST API returns an error or invalid response."""


class EngramClient:
    """Thin synchronous client for Engram's REST API.

    The client intentionally uses the standard library so integrations can use
    Engram without adding another required HTTP dependency.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7474",
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def query(
        self,
        topic: str,
        *,
        scope: str | None = None,
        limit: int = 10,
        as_of: str | None = None,
        fact_type: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query Engram memory for facts relevant to a topic."""
        payload: dict[str, Any] = {"topic": topic, "limit": limit}
        if scope:
            payload["scope"] = scope
        if as_of:
            payload["as_of"] = as_of
        if fact_type:
            payload["fact_type"] = fact_type
        if agent_id:
            payload["agent_id"] = agent_id
        result = self._request_json("POST", "/api/query", payload)
        if not isinstance(result, list):
            raise EngramClientError("Expected /api/query to return a JSON list.")
        return result

    def commit(
        self,
        content: str,
        *,
        scope: str = "general",
        confidence: float = 0.8,
        agent_id: str | None = None,
        engineer: str | None = None,
        provenance: str | None = None,
        fact_type: str = "observation",
        ttl_days: int | None = None,
        operation: str = "add",
    ) -> dict[str, Any]:
        """Commit a verified fact to Engram memory."""
        payload: dict[str, Any] = {
            "content": content,
            "scope": scope,
            "confidence": confidence,
            "fact_type": fact_type,
            "operation": operation,
        }
        if agent_id:
            payload["agent_id"] = agent_id
        if engineer:
            payload["engineer"] = engineer
        if provenance:
            payload["provenance"] = provenance
        if ttl_days is not None:
            payload["ttl_days"] = ttl_days
        result = self._request_json("POST", "/api/commit", payload)
        if not isinstance(result, dict):
            raise EngramClientError("Expected /api/commit to return a JSON object.")
        return result

    def batch_commit(
        self,
        facts: list[dict[str, Any]],
        *,
        agent_id: str | None = None,
        engineer: str | None = None,
    ) -> dict[str, Any]:
        """Commit multiple verified facts in one request."""
        payload: dict[str, Any] = {"facts": facts}
        if agent_id:
            payload["agent_id"] = agent_id
        if engineer:
            payload["engineer"] = engineer
        result = self._request_json("POST", "/api/batch-commit", payload)
        if not isinstance(result, dict):
            raise EngramClientError("Expected /api/batch-commit to return a JSON object.")
        return result

    def conflicts(self, *, scope: str | None = None, status: str = "open") -> list[dict[str, Any]]:
        """Return Engram conflicts, optionally filtered by scope/status."""
        params = {"status": status}
        if scope:
            params["scope"] = scope
        path = f"/api/conflicts?{urllib.parse.urlencode(params)}"
        result = self._request_json("GET", path)
        if not isinstance(result, list):
            raise EngramClientError("Expected /api/conflicts to return a JSON list.")
        return result

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")
            raise EngramClientError(
                _extract_error(raw_error) or f"Engram API error: {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise EngramClientError(f"Could not reach Engram API: {exc.reason}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EngramClientError("Engram API returned invalid JSON.") from exc


def _extract_error(raw_error: str) -> str | None:
    try:
        payload = json.loads(raw_error)
    except json.JSONDecodeError:
        return raw_error.strip() or None
    if isinstance(payload, dict):
        error = payload.get("error") or payload.get("detail")
        return str(error) if error else None
    return None
