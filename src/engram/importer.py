"""Document importer for seeding Engram from existing Markdown/text files."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engram.engine import EngramEngine

logger = logging.getLogger("engram")

SUPPORTED_EXTENSIONS = {".md", ".txt"}
SKIPPED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}
DEFAULT_CONFIDENCE = 0.7
DEFAULT_FACT_TYPE = "observation"
DEFAULT_AGENT_ID = "engram-import"
DEFAULT_MAX_CHARS = 4000


@dataclass
class ImportIssue:
    source: str
    message: str


@dataclass
class ImportSummary:
    files_scanned: int = 0
    facts_extracted: int = 0
    committed: int = 0
    duplicates: int = 0
    skipped: int = 0
    errors: list[ImportIssue] = field(default_factory=list)
    dry_run_facts: list[dict[str, Any]] = field(default_factory=list)


def discover_import_files(path: Path, pattern: str = "*") -> list[Path]:
    """Return supported Markdown/text files under *path* in stable order."""
    path = path.expanduser()
    if path.is_file():
        return [path] if _is_supported_file(path, pattern) else []
    if not path.exists():
        raise FileNotFoundError(f"Import path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Import path is not a file or directory: {path}")

    files: list[Path] = []
    for candidate in path.rglob(pattern):
        if any(part in SKIPPED_DIRS or part.startswith(".") for part in candidate.parts):
            continue
        if _is_supported_file(candidate, pattern):
            files.append(candidate)
    return sorted(files)


def read_text_file(path: Path) -> str:
    """Read a text file, replacing invalid bytes rather than aborting the import."""
    return path.read_text(encoding="utf-8", errors="replace")


def chunk_document(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Split Markdown/text into chunks small enough for extraction."""
    blocks = _split_markdown_blocks(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        chunk = "\n\n".join(current).strip()
        if chunk:
            chunks.append(chunk)
        current = []
        current_len = 0

    for block in blocks:
        if len(block) > max_chars:
            flush()
            chunks.extend(_split_long_block(block, max_chars=max_chars))
            continue

        proposed_len = current_len + len(block) + (2 if current else 0)
        if current and proposed_len > max_chars:
            flush()

        current.append(block)
        current_len += len(block) + (2 if current_len else 0)

    flush()
    return chunks


async def extract_atomic_statements(chunk: str, source: str) -> list[str]:
    """Extract atomic statements from a document chunk.

    Uses Anthropic Haiku when ANTHROPIC_API_KEY and the optional dependency are
    available. Otherwise falls back to conservative paragraph/bullet extraction.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _heuristic_extract_atomic_statements(chunk)

    try:
        import anthropic
    except ImportError:
        logger.debug("anthropic package not installed; using heuristic import extraction")
        return _heuristic_extract_atomic_statements(chunk)

    client = anthropic.AsyncAnthropic(api_key=api_key)
    prompt = (
        "Extract atomic, durable engineering knowledge from this document chunk.\n"
        "Return JSON only, as an array of short factual strings. Do not invent facts. "
        "Omit vague, promotional, or duplicate statements.\n\n"
        f"Source: {source}\n\n"
        f"Document chunk:\n{chunk}"
    )
    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return _clean_statements(str(item) for item in data)
    except Exception:
        logger.exception("LLM import extraction failed for %s", source)
        return _heuristic_extract_atomic_statements(chunk)


def prepare_import_fact(statement: str, source: str, scope: str) -> dict[str, Any]:
    """Build a fact payload for EngramEngine.commit_batch()."""
    return {
        "content": statement,
        "scope": scope,
        "confidence": DEFAULT_CONFIDENCE,
        "fact_type": DEFAULT_FACT_TYPE,
        "provenance": source,
    }


async def import_documents(
    engine: EngramEngine,
    path: Path,
    *,
    scope: str = "imported",
    pattern: str = "*",
    dry_run: bool = False,
) -> ImportSummary:
    """Import supported documents from *path* into Engram."""
    summary = ImportSummary()
    files = await asyncio.to_thread(discover_import_files, path, pattern=pattern)
    summary.files_scanned = len(files)

    for file_path in files:
        try:
            text = await asyncio.to_thread(read_text_file, file_path)
            chunks = chunk_document(text)
            file_facts: list[dict[str, Any]] = []

            for chunk in chunks:
                statements = await extract_atomic_statements(chunk, str(file_path))
                for statement in statements:
                    file_facts.append(prepare_import_fact(statement, str(file_path), scope))

            summary.facts_extracted += len(file_facts)

            if dry_run:
                summary.dry_run_facts.extend(file_facts)
                continue

            results = await engine.commit_batch(
                file_facts,
                scope=scope,
                agent_id=DEFAULT_AGENT_ID,
            )
            for result in results:
                if result.get("success") and result.get("duplicate"):
                    summary.duplicates += 1
                elif result.get("success"):
                    summary.committed += 1
                else:
                    summary.skipped += 1
                    summary.errors.append(
                        ImportIssue(str(file_path), str(result.get("error", "unknown error")))
                    )
        except Exception as exc:
            summary.skipped += 1
            summary.errors.append(ImportIssue(str(file_path), str(exc)))

    return summary


def _is_supported_file(path: Path, pattern: str) -> bool:
    return path.is_file() and path.match(pattern) and path.suffix.lower() in SUPPORTED_EXTENSIONS


def _split_markdown_blocks(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized)
    return [block.strip() for block in blocks if block.strip()]


def _split_long_block(block: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", block)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current.strip())
    return chunks


def _heuristic_extract_atomic_statements(chunk: str) -> list[str]:
    lines: list[str] = []
    for raw_line in chunk.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        if line:
            lines.append(line)

    if not lines:
        return []

    candidates = re.split(r"(?<=[.!?])\s+", " ".join(lines))
    return _clean_statements(candidates)


def _clean_statements(statements: Any) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for statement in statements:
        text = " ".join(str(statement).split())
        if len(text) < 12:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned
