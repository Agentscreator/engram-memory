"""PR scanner helpers — query building and comment formatting.

Extracted as a Python module so the logic is testable independently
of the shell script that orchestrates the GitHub Action.
"""

from __future__ import annotations

import re


def build_query(title: str, body: str, changed_files: list[str], max_len: int = 500) -> str:
    """Build a search query from PR context.

    Combines the PR title, a cleaned snippet of the body, and unique
    directory paths from changed files into a single string suitable
    for Engram's ``POST /api/query`` ``topic`` parameter.
    """
    parts: list[str] = []

    if title and title.strip():
        parts.append(title.strip())

    if body and body.strip():
        clean = re.sub(r"[#*`>_~\[\]]", "", body)
        clean = clean.strip()[:200]
        if clean:
            parts.append(clean)

    if changed_files:
        import os

        dirs = sorted({os.path.dirname(f) for f in changed_files[:10] if f})
        dirs = [d for d in dirs if d]
        if dirs:
            parts.append(" ".join(dirs))

    query = " ".join(parts).strip()
    return query[:max_len]


def format_comment(
    facts: list[dict],
    relevance_threshold: float = 0.3,
) -> str:
    """Format matching facts into a GitHub PR comment (Markdown).

    Returns an empty string if no facts are provided.
    """
    if not facts:
        return ""

    lines: list[str] = [
        "### Engram Memory Check",
        "",
        f"Found **{len(facts)}** fact(s) in workspace memory that may be relevant to this PR.",
        "Review these before merging to avoid contradicting established team knowledge.",
        "",
        "| Fact | Scope | Agent | Confidence | Date |",
        "|------|-------|-------|------------|------|",
    ]

    for fact in facts:
        content = (fact.get("content") or "")[:120].replace("|", "\\|")
        scope = fact.get("scope") or "-"
        agent = fact.get("agent_id") or "unknown"
        confidence = fact.get("confidence", 0)
        date = (fact.get("committed_at") or "-")[:10]

        lines.append(f"| {content} | `{scope}` | `{agent}` | {confidence} | {date} |")

    lines.append("")
    lines.append("---")
    lines.append(
        f"<sub>Scanned by [Engram](https://github.com/Agentscreator/Engram) · "
        f"Relevance threshold: {relevance_threshold} · "
        f"[What is this?](https://github.com/Agentscreator/Engram/blob/main/docs/pr-scanner.md)</sub>"
    )

    return "\n".join(lines)


def filter_by_relevance(facts: list[dict], threshold: float) -> list[dict]:
    """Return facts with relevance_score >= threshold."""
    return [f for f in facts if (f.get("relevance_score") or 0) >= threshold]
