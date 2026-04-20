"""Phase 5 — Authentication and access control.

Three tiers:
  Tier 1 — Local mode (default): No auth. Stdio transport.
  Tier 2 — Team mode (--auth): Bearer JWT tokens bound to server instance.
  Tier 3 — Enterprise mode (future): Full OAuth 2.1 with PKCE.

Rate limiting: per-agent commit rate limits (configurable, default 50/hour).
Scope permissions: hierarchical, temporal, checked on every tool call.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("engram")

# ── JWT-like token handling (minimal, no external dep) ───────────────

_SECRET_KEY: str | None = None
_TOKEN_AUDIENCE = "engram-mcp"


def _get_secret_key() -> str:
    """Get or generate the server signing key."""
    global _SECRET_KEY
    if _SECRET_KEY:
        return _SECRET_KEY
    key_path = Path.home() / ".engram" / ".server_key"
    if key_path.exists():
        _SECRET_KEY = key_path.read_text().strip()
    else:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_KEY = hashlib.sha256(os.urandom(64)).hexdigest()
        key_path.write_text(_SECRET_KEY)
        key_path.chmod(0o600)
    return _SECRET_KEY


def _b64url_encode(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    import base64

    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_token(
    engineer: str,
    agent_id: str | None = None,
    expires_hours: int = 720,  # 30 days default
) -> str:
    """Create a signed bearer token for an engineer."""
    secret = _get_secret_key()
    now = int(time.time())
    payload = {
        "sub": engineer,
        "aud": _TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + expires_hours * 3600,
    }
    if agent_id:
        payload["agent_id"] = agent_id

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload).encode())
    sig_input = f"{header}.{body}"
    signature = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).digest()
    sig = _b64url_encode(signature)
    return f"{header}.{body}.{sig}"


def verify_token(token: str) -> dict[str, Any] | None:
    """Verify a bearer token. Returns payload dict or None if invalid."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, body_b64, sig_b64 = parts
        secret = _get_secret_key()
        sig_input = f"{header_b64}.{body_b64}"
        expected_sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).digest()
        actual_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_b64url_decode(body_b64))
        if payload.get("aud") != _TOKEN_AUDIENCE:
            return None
        if payload.get("exp", 0) <= int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ── Rate Limiter ─────────────────────────────────────────────────────


class RateLimiter:
    """Per-agent sliding window rate limiter."""

    def __init__(self, max_per_hour: int = 50) -> None:
        self.max_per_hour = max_per_hour
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, agent_id: str) -> bool:
        """Return True if the agent is within rate limits."""
        now = time.time()
        cutoff = now - 3600
        window = self._windows[agent_id]
        # Prune old entries
        self._windows[agent_id] = [t for t in window if t > cutoff]
        return len(self._windows[agent_id]) < self.max_per_hour

    def record(self, agent_id: str) -> None:
        """Record a commit for rate limiting."""
        self._windows[agent_id].append(time.time())


class CommitVelocityAnomalyDetector:
    """Detect abnormal commit patterns per agent.

    Flags agents that exceed a commit velocity threshold within
    a short time window, indicating potential MINJA attacks.
    """

    def __init__(
        self,
        threshold: int = 10,
        window_seconds: float = 60.0,
    ) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self._recent_commits: dict[str, list[float]] = defaultdict(list)

    def record(self, agent_id: str) -> bool:
        """Record a commit and check for anomalies.

        Returns True if recording succeeded (no anomaly detected).
        Returns False if anomaly detected (at or above threshold).
        """
        now = time.time()
        cutoff = now - self.window_seconds
        self._recent_commits[agent_id] = [t for t in self._recent_commits[agent_id] if t > cutoff]
        # Block if already at or above threshold before adding
        if len(self._recent_commits[agent_id]) >= self.threshold:
            logger.warning(
                "Anomalous commit velocity detected for agent %s: %d commits in last %.0f seconds",
                agent_id,
                len(self._recent_commits[agent_id]),
                self.window_seconds,
            )
            return False
        self._recent_commits[agent_id].append(now)
        return True

    def is_anomalous(self, agent_id: str) -> bool:
        """Return True if agent has anomalous commit velocity."""
        if agent_id not in self._recent_commits:
            return False
        now = time.time()
        cutoff = now - self.window_seconds
        active_commits = [t for t in self._recent_commits[agent_id] if t > cutoff]
        return len(active_commits) >= self.threshold

    def reset(self, agent_id: str) -> None:
        """Reset the commit history for an agent."""
        self._recent_commits[agent_id].clear()

    def get_velocity(self, agent_id: str) -> int:
        """Get the current commit velocity (commits in window)."""
        if agent_id not in self._recent_commits:
            return 0
        now = time.time()
        cutoff = now - self.window_seconds
        return len([t for t in self._recent_commits[agent_id] if t > cutoff])


# ── Scope Permission Checker ─────────────────────────────────────────


async def check_scope_permission(
    storage: Any,
    agent_id: str,
    scope: str,
    action: str = "read",
) -> bool:
    """Check if an agent has permission for a scope.

    Hierarchical: 'payments/webhooks' inherits from 'payments'.
    Default (no row): full access.
    Temporal: permissions carry valid_from/valid_until windows.
    """
    perm = await storage.get_scope_permission(agent_id, scope)
    if perm is None:
        # Check parent scopes
        parts = scope.split("/")
        for i in range(len(parts) - 1, 0, -1):
            parent = "/".join(parts[:i])
            perm = await storage.get_scope_permission(agent_id, parent)
            if perm is not None:
                break
    if perm is None:
        return True  # Default: full access

    # Check temporal validity
    now = datetime.now(timezone.utc).isoformat()
    if perm.get("valid_from") and perm["valid_from"] > now:
        return True  # Permission not yet active, use default
    if perm.get("valid_until") and perm["valid_until"] < now:
        return True  # Permission expired, use default

    if action == "read":
        return bool(perm.get("can_read", True))
    elif action == "write":
        return bool(perm.get("can_write", True))
    return True
