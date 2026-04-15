"""Helpers for checking staged commits against Engram workspace memory."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any


def mcp_url_to_base_url(url: str) -> str:
    """Convert an MCP endpoint URL into the corresponding REST base URL."""
    url = url.strip()
    if url.endswith("/mcp"):
        return url[: -len("/mcp")]
    return url


def load_credentials(cwd: Path | None = None) -> tuple[str, str]:
    """Load Engram server URL and invite key from env and local credential files."""
    cwd = cwd or Path.cwd()

    server_url = os.environ.get("ENGRAM_SERVER_URL", "").strip()
    mcp_url = os.environ.get("ENGRAM_MCP_URL", "").strip()
    invite_key = os.environ.get("ENGRAM_INVITE_KEY", "").strip()

    for path in (Path.home() / ".engram" / "credentials", cwd / ".engram.env"):
        if not path.exists():
            continue
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if line.startswith("ENGRAM_SERVER_URL="):
                server_url = line[len("ENGRAM_SERVER_URL=") :].strip()
            elif line.startswith("ENGRAM_MCP_URL="):
                mcp_url = line[len("ENGRAM_MCP_URL=") :].strip()
            elif line.startswith("ENGRAM_INVITE_KEY="):
                invite_key = line[len("ENGRAM_INVITE_KEY=") :].strip()

    if not server_url:
        server_url = mcp_url_to_base_url(mcp_url) if mcp_url else "http://127.0.0.1:7474"

    return server_url.rstrip("/"), invite_key


def run_git_command(args: list[str]) -> str:
    """Run a git command and return stdout or raise a RuntimeError."""
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip() or "git command failed"
        raise RuntimeError(message)
    return proc.stdout


def get_staged_files() -> list[str]:
    """Return the list of staged files."""
    output = run_git_command(["diff", "--cached", "--name-only"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def get_staged_diff() -> str:
    """Return the staged diff without color codes."""
    return run_git_command(["diff", "--cached", "--unified=0", "--no-color"])


def summarize_staged_diff(diff_text: str, max_lines: int = 20, max_chars: int = 800) -> str:
    """Extract changed content lines from a staged diff for use in semantic search."""
    summary_lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith(("diff --git", "index ", "@@", "+++", "---")):
            continue
        if not line.startswith(("+", "-")):
            continue
        clean = line[1:].strip()
        if clean:
            summary_lines.append(clean)
        if len(summary_lines) >= max_lines:
            break
    summary = re.sub(r"\s+", " ", " ".join(summary_lines)).strip()
    return summary[:max_chars]


def _file_context(changed_files: list[str], max_items: int = 10) -> str:
    contexts: list[str] = []
    seen: set[str] = set()
    for file_path in changed_files[:max_items]:
        path = Path(file_path)
        context = path.parent.as_posix() if path.parent.as_posix() != "." else path.name
        if context and context not in seen:
            contexts.append(context)
            seen.add(context)
    return " ".join(contexts)


def build_commit_query(
    commit_message: str | None,
    changed_files: list[str],
    staged_diff: str,
    max_len: int = 1200,
) -> str:
    """Build a search query from commit context."""
    parts: list[str] = []

    if commit_message and commit_message.strip():
        parts.append(commit_message.strip())

    file_context = _file_context(changed_files)
    if file_context:
        parts.append(file_context)

    diff_summary = summarize_staged_diff(staged_diff)
    if diff_summary:
        parts.append(diff_summary)

    query = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return query[:max_len]


def query_workspace(
    base_url: str,
    invite_key: str,
    topic: str,
    limit: int = 5,
    timeout: int = 10,
) -> list[dict[str, Any]]:
    """Call Engram's REST query endpoint and return matching facts."""
    payload = json.dumps({"topic": topic, "limit": limit}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if invite_key:
        headers["Authorization"] = f"Bearer {invite_key}"

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/query",
        data=payload,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def filter_relevant_facts(
    facts: list[dict[str, Any]],
    threshold: float,
) -> list[dict[str, Any]]:
    """Filter query results by relevance threshold."""
    return [fact for fact in facts if float(fact.get("relevance_score") or 0) >= threshold]


def format_commit_warning(
    facts: list[dict[str, Any]],
    threshold: float,
    strict: bool = False,
) -> str:
    """Format a terminal warning message for commit-time checks."""
    if not facts:
        return "No relevant Engram facts found for this commit."

    lines = [
        f"Engram commit check found {len(facts)} potentially relevant fact(s).",
        "Review these before committing to avoid contradicting workspace memory.",
        "",
    ]

    for idx, fact in enumerate(facts, start=1):
        content = (fact.get("content") or "").strip()
        scope = fact.get("scope") or "-"
        agent_id = fact.get("agent_id") or "unknown"
        committed_at = str(fact.get("committed_at") or "-")[:10]
        confidence = fact.get("confidence", 0)
        relevance = fact.get("relevance_score", 0)

        lines.append(f"{idx}. [{scope}] {content}")
        lines.append(
            "   "
            f"agent={agent_id} confidence={confidence} relevance={relevance} committed_at={committed_at}"
        )

    lines.append("")
    lines.append(f"Relevance threshold: {threshold}")
    if strict:
        lines.append("Strict mode enabled: exiting non-zero because relevant facts were found.")
    else:
        lines.append("Advisory only: commit can continue.")
        lines.append("Use --strict to block when relevant facts are found.")

    return "\n".join(lines)
