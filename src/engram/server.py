"""Engram MCP Server.

Core tools:
  engram_status           — check setup state; guides agent through onboarding
  engram_init             — founder creates a new workspace (requires ENGRAM_DB_URL)
  engram_join             — teammate joins an existing workspace via Invite Key
  engram_reset_invite_key — creator resets the invite key after a security breach
  engram_commit           — write a verified fact to shared memory
  engram_query            — read what the team's agents collectively know
  engram_conflicts        — surface contradictions between facts
  engram_resolve          — settle a disagreement
  engram_stats            — inspect privacy-preserving workspace analytics

Tool descriptions embed behavioral guidance for the LLM.
The 'next_prompt' field in onboarding responses tells the agent exactly what to say.

API Versioning:
  - Tool API version: 1.0 (stable)
  - Add '?version=latest' to tool calls for newest version
  - Deprecated tools will be removed after 6 months notice
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Literal

# API version constant - bump for breaking changes
__version__ = "1.0.0"
__api_version__ = "1.0"

from mcp.server.fastmcp import FastMCP

from engram.engine import EngramEngine
from engram.storage import BaseStorage
from engram.tool_version import deprecation_warning, tool_surface_metadata

logger = logging.getLogger("engram")

mcp = FastMCP(
    "Engram",
    instructions=(
        "Engram is a shared team memory layer with conflict detection. "
        "IMPORTANT: On your very first tool call in a new session, call engram_status() "
        "to check if the workspace is configured. "
        "Read the 'next_prompt' field in every response from engram_status, engram_init, "
        "and engram_join — say that text to the user verbatim. Follow each prompt in sequence. "
        "Once status is 'ready': call engram_query before starting any task, "
        "check engram_conflicts before architectural decisions. "
        "Use engram_commit to record verified discoveries, decisions, and corrections — "
        "not raw user messages. User messages are captured automatically by IDE-level hooks."
    ),
)

# Engine and storage are initialized at startup via cli.py
_engine: EngramEngine | None = None
_storage: BaseStorage | None = None
_rate_limiter: Any = None

# In-memory query tracking for loop detection (Issue #66)
# Tracks queries per agent per session to detect repeated queries
_query_history: dict[str, list[str]] = {}  # agent_id -> list of query topics


def get_engine() -> EngramEngine:
    if _engine is None:
        raise RuntimeError("Engram engine not initialized.")
    return _engine


def set_auth_enabled(enabled: bool) -> None:
    global _auth_enabled
    _auth_enabled = enabled


def set_rate_limiter(limiter: Any) -> None:
    global _rate_limiter
    _rate_limiter = limiter


_ENGRAM_ENV_FILENAME = ".engram.env"


def _read_engram_env() -> str | None:
    """Read ENGRAM_INVITE_KEY from .engram.env in the current working directory."""
    env_path = Path.cwd() / _ENGRAM_ENV_FILENAME
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("ENGRAM_INVITE_KEY="):
            return line[len("ENGRAM_INVITE_KEY=") :].strip()
    return None


_CREDENTIALS_CONTENT_TEMPLATE = """\
# Engram — Global Credentials
# Written by engram join / engram init.
# Read by the Claude Code UserPromptSubmit hook (~/.engram/hooks/auto_commit.py)
# to auto-commit every user message to shared memory at the shell level.
#
# Keep this file private — it contains workspace credentials.
ENGRAM_SERVER_URL={server_url}
ENGRAM_INVITE_KEY={invite_key}
"""


def _write_global_credentials(
    invite_key: str, server_url: str = "https://www.engram-memory.com"
) -> None:
    """Write ~/.engram/credentials for the shell-level auto-commit hook."""
    creds_path = Path.home() / ".engram" / "credentials"
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(
        _CREDENTIALS_CONTENT_TEMPLATE.format(server_url=server_url, invite_key=invite_key)
    )
    creds_path.chmod(0o600)
    logger.info("Wrote global credentials to %s", creds_path)


def _write_engram_env(invite_key: str, server_url: str = "https://www.engram-memory.com") -> None:
    """Write .engram.env to the current working directory and global credentials."""
    env_path = Path.cwd() / _ENGRAM_ENV_FILENAME
    content = (
        "# Engram — Shared Team Memory\n"
        "# This file allows all AI agents in this workspace to connect to\n"
        "# the team's shared Engram memory automatically.\n"
        "#\n"
        "# MCP agents (Claude Code, Cursor, Windsurf): engram_status() reads this\n"
        "# file and auto-joins the workspace at session start.\n"
        "#\n"
        "# Non-MCP agents: use ENGRAM_SERVER_URL + ENGRAM_INVITE_KEY directly\n"
        "# via the REST API (see AGENTS.md for instructions).\n"
        "#\n"
        "# DO NOT DELETE — without this file, agents lose access to shared memory.\n"
        "# Add .engram.env to your .gitignore — it contains credentials.\n"
        f"ENGRAM_SERVER_URL={server_url}\n"
        f"ENGRAM_INVITE_KEY={invite_key}\n"
    )
    env_path.write_text(content)
    env_path.chmod(0o600)
    logger.info("Wrote %s", env_path)
    _write_global_credentials(invite_key, server_url)


async def _join_workspace(invite_key: str) -> dict[str, Any]:
    """Core join logic shared by engram_join and the auto-join in engram_status."""
    from engram.workspace import (
        WorkspaceConfig,
        decode_invite_key,
        invite_key_hash,
        write_workspace,
    )

    try:
        payload = decode_invite_key(invite_key)
    except ValueError as e:
        return {
            "status": "error",
            "next_prompt": (
                f"That invite key isn't valid: {e}\n\n"
                "Please double-check it with the person who set up the workspace."
            ),
        }

    db_url = payload.get("db_url", "")
    engram_id = payload.get("engram_id", "")
    if not db_url or not engram_id:
        return {
            "status": "error",
            "next_prompt": (
                "This invite key does not contain embedded database credentials. "
                "It may be a cloud-issued key — connect via the Engram dashboard instead."
            ),
        }
    schema = payload.get("schema", "engram")
    key_generation = payload.get("key_generation", 0)

    key_hash = invite_key_hash(invite_key)
    try:
        from engram.postgres_storage import PostgresStorage

        target_storage = PostgresStorage(db_url=db_url, workspace_id=engram_id, schema=schema)
        await target_storage.connect()
        consumed = await target_storage.consume_invite_key(key_hash)
        await target_storage.close()
    except Exception:
        consumed = None

    if consumed is None:
        return {
            "status": "error",
            "next_prompt": (
                "This invite key has been revoked, used up, or expired. "
                "Ask the workspace creator to generate a new one with engram_reset_invite_key."
            ),
        }

    config = WorkspaceConfig(
        engram_id=engram_id,
        db_url=db_url,
        schema=schema,
        anonymous_mode=False,
        anon_agents=False,
        key_generation=key_generation,
        is_creator=False,
    )
    write_workspace(config)
    _write_engram_env(invite_key)
    logger.info(
        "Joined workspace: %s (schema: %s, generation: %d)", engram_id, schema, key_generation
    )

    return {
        "status": "joined",
        "engram_id": engram_id,
        "schema": schema,
    }


_DISCONNECTED_NEXT_PROMPT = (
    "Your Engram client has been temporarily disconnected due to a security key reset.\n\n"
    "The workspace creator has issued a new invite key. To reconnect:\n\n"
    "1. Obtain the new invite key from your workspace creator.\n"
    "2. Call engram_join with the new invite key.\n"
    "3. Restart your MCP client (Claude Code / Claude Desktop / IDE extension).\n\n"
    "Until you reconnect, Engram operations are suspended for your agent."
)


async def _check_key_generation(ws: Any) -> dict[str, Any] | None:
    """Return a disconnected response if the local key_generation is behind the DB.

    When an invite key rotation has been performed with a grace period, agents
    whose generation is behind are allowed to continue until the grace window
    expires — only then do they receive the disconnected response.

    Returns None if the generation is current (or within grace), or if the
    check cannot be performed (local mode, storage not ready).
    """
    if _storage is None or not ws or not ws.db_url:
        return None
    db_gen = await _storage.get_key_generation(ws.engram_id)
    if db_gen <= ws.key_generation:
        return None
    # Generation is behind — check whether a grace window is still active.
    grace_until = await _storage.get_active_grace_until(ws.engram_id)
    if grace_until is not None:
        now_iso = datetime.now(timezone.utc).isoformat()
        if grace_until > now_iso:
            # Within grace window — existing session may continue.
            return None
    return {
        "status": "disconnected",
        "next_prompt": _DISCONNECTED_NEXT_PROMPT,
        **tool_surface_metadata(),
    }


# ── engram_status ─────────────────────────────────────────────────────


async def _conflict_detection_summary() -> dict[str, Any]:
    """Return conflict detection counters for status observability."""
    fallback: dict[str, Any] = {
        "status": "unavailable",
        "open": 0,
        "resolved": 0,
        "dismissed": 0,
        "total": 0,
        "by_tier": {},
        "by_type": {},
    }
    try:
        stats = await get_engine().get_stats()
    except Exception as exc:
        logger.debug("Conflict detection stats unavailable: %s", exc)
        return fallback

    conflicts = stats.get("conflicts") or {}
    return {
        "status": "available",
        "open": conflicts.get("open", 0),
        "resolved": conflicts.get("resolved", 0),
        "dismissed": conflicts.get("dismissed", 0),
        "total": conflicts.get("total", 0),
        "by_tier": conflicts.get("by_tier", {}),
        "by_type": conflicts.get("by_type", {}),
    }


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
async def engram_status() -> dict[str, Any]:
    """Check whether Engram is configured and get the next setup step.

    **Precondition:** Call this FIRST in every new session before any other tool.

    **When to call:**
    - At the start of every agent session
    - After any error or unexpected state

    **Returns:** {status, next_prompt?, engram_id?, mode?, schema?, anonymous_mode?}

    Example: {"status": "ready", "mode": "team", "engram_id": "ENG-XXXXXX", "schema": "engram"}

    When status is 'ready': call engram_query before starting any task,
    and use engram_commit to record verified discoveries and decisions.

    **What NOT to do:**
    - Don't skip this and call engram_query directly — you may be disconnected
    - Don't assume status is 'ready' without checking first

    **Common mistake:** Starting tasks without calling engram_status first, leading to
    "disconnected" errors mid-task.

    **API Version:** This tool is part of API version 1.0 (stable).
    """
    from engram.workspace import read_workspace, WORKSPACE_PATH

    # ── 1. Auto-join via .engram.env if workspace not yet configured ──────
    env_key = _read_engram_env()
    ws = read_workspace()

    if env_key and not (ws and (ws.db_url or WORKSPACE_PATH.exists())):
        try:
            result = await _join_workspace(env_key)
            if result["status"] == "joined":
                ws = read_workspace()  # reload after join
            # On error status, fall through to unconfigured
        except Exception as exc:
            logger.warning("Auto-join from .engram.env failed: %s", exc)

    # Reload ws after potential auto-join
    if ws is None:
        ws = read_workspace()

    if ws and ws.db_url:
        disconnected = await _check_key_generation(ws)
        if disconnected:
            return disconnected

        # Auto-generate .engram.env if missing so future agents can auto-join
        if env_key is None and _storage is not None:
            try:
                from engram.workspace import generate_invite_key
                import time

                new_key, key_hash = generate_invite_key(
                    db_url=ws.db_url,
                    engram_id=ws.engram_id,
                    schema=ws.schema,
                    expires_days=90,
                    uses_remaining=50,
                    key_generation=ws.key_generation,
                )
                expires_ts = datetime.fromtimestamp(
                    time.time() + 90 * 86400, tz=timezone.utc
                ).isoformat()
                await _storage.insert_invite_key(
                    key_hash=key_hash,
                    engram_id=ws.engram_id,
                    expires_at=expires_ts,
                    uses_remaining=50,
                )
                _write_engram_env(new_key)
            except Exception as exc:
                logger.warning("Could not auto-generate .engram.env: %s", exc)

        return {
            "status": "ready",
            "mode": "team",
            "engram_id": ws.engram_id,
            "schema": ws.schema,
            "anonymous_mode": ws.anonymous_mode,
            "conflict_detection": await _conflict_detection_summary(),
            "next_prompt": (
                "Engram is connected and ready.\n\n"
                "User messages are captured automatically by IDE-level hooks. "
                "Use engram_commit to record verified discoveries, decisions, "
                "and corrections — not raw user messages.\n\n"
                "Before starting any task, call engram_query to check what the "
                "team already knows. Before architectural decisions, call "
                "engram_conflicts to surface contradictions."
            ),
            **tool_surface_metadata(),
        }

    if ws and not ws.db_url and WORKSPACE_PATH.exists():
        return {
            "status": "ready",
            "mode": "local",
            "engram_id": "local",
            "conflict_detection": await _conflict_detection_summary(),
            "next_prompt": (
                "Engram is connected and ready (local mode).\n\n"
                "User messages are captured automatically by IDE-level hooks. "
                "Use engram_commit to record verified discoveries, decisions, "
                "and corrections — not raw user messages.\n\n"
                "Before starting any task, call engram_query to check what the "
                "team already knows."
            ),
            **tool_surface_metadata(),
        }

    db_url = os.environ.get("ENGRAM_DB_URL", "")
    if db_url:
        return {
            "status": "db_url_detected",
            **tool_surface_metadata(),
            "next_prompt": (
                "I detected a database connection string in your environment.\n\n"
                "What would you like to do?\n\n"
                "- **Join an existing workspace** — paste your Invite Key (format: ek_live_...).\n"
                "- **Create a new workspace** — say 'create' and I'll run `engram init` to set one up "
                "and generate an invite key you can share with your team.\n\n"
                "Note: Engram will create its tables in a separate 'engram' schema "
                "in your database, so it won't interfere with your application tables."
            ),
        }

    return {
        "status": "unconfigured",
        **tool_surface_metadata(),
        "next_prompt": (
            "Welcome to Engram — shared memory for your team's agents.\n\n"
            "• Create a workspace at https://www.engram-memory.com/dashboard\n"
            "• Join a workspace you already created — paste your invite key from the dashboard\n"
            "• Join a teammate's workspace — paste the invite key they shared with you\n\n"
            "Self-hosted options:\n"
            "• PostgreSQL — set ENGRAM_DB_URL in your environment, then say 'create'\n"
            "• SQLite (local only) — say 'create' for solo use"
        ),
    }


# ── engram_init ───────────────────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
async def engram_init(
    anonymous_mode: bool = False,
    anon_agents: bool = False,
    invite_expires_days: int = 90,
    invite_uses: int = 10,
    schema: str = "engram",
) -> dict[str, Any]:
    """Set up a new Engram workspace (team founder only).

    **Precondition:** ENGRAM_DB_URL must be set in your environment.

    **When to call:**
    - When you're the first team member setting up shared memory
    - After engram_status returns "unconfigured" or "awaiting_db"

    **What NOT to do:**
    - Don't call this if you're joining an existing workspace — use engram_join instead
    - Don't paste database credentials in chat — use environment variables
    - Don't set up workspaces for others — give them the invite key instead

    **Common mistake:** Setting up a new workspace when you should join an existing one.
    Only call this if you're the workspace founder. Teammates should use engram_join.

    The invite key contains the database URL encrypted inside it —
    teammates only need the Team ID and Invite Key (not the db URL).

    Parameters:
    - anonymous_mode: If true, engineer names are stripped from all commits.
      Ask the user: "Should commits show who made them, or stay anonymous?"
    - anon_agents: If true, agent IDs are randomized each session.
    - invite_expires_days: How long the invite key is valid (default 90 days).
    - invite_uses: How many times the invite key can be used (default 10).
    - schema: PostgreSQL schema name for Engram tables (default "engram").
      Engram creates all tables in this schema to avoid conflicts with
      your application tables.

    Returns: {status, engram_id, invite_key, next_prompt}

    Example: {"status": "initialized", "engram_id": "ENG-XXXXXX", "invite_key": "ek_live_..."}
    """
    db_url = os.environ.get("ENGRAM_DB_URL", "")
    if not db_url:
        # Check if .env file exists in current directory
        env_file = Path.cwd() / ".env"
        env_exists = env_file.exists()

        return {
            "status": "awaiting_db",
            "next_prompt": (
                "To set up Engram, add your database connection string to your environment.\n\n"
                + (
                    f"I see you have a .env file at {env_file}. Add this line:\n\n"
                    "  ENGRAM_DB_URL='postgres://user:password@host:port/database'\n\n"
                    if env_exists
                    else "Create a .env file in your project root with:\n\n"
                    "  ENGRAM_DB_URL='postgres://user:password@host:port/database'\n\n"
                    "Or set it in your shell config (.bashrc, .zshrc, etc.):\n\n"
                    "  export ENGRAM_DB_URL='postgres://user:password@host:port/database'\n\n"
                )
                + "IMPORTANT: Don't paste your database URL in this chat for security reasons.\n\n"
                "You can:\n"
                "  • Use your existing app database (Engram creates a separate 'engram' schema)\n"
                "  • Get a free dedicated database at neon.tech, supabase.com, or railway.app\n\n"
                "Once set, restart this chat and I'll detect it automatically."
            ),
        }

    from engram.workspace import (
        WorkspaceConfig,
        generate_invite_key,
        generate_team_id,
        write_workspace,
    )

    engram_id = generate_team_id()
    invite_key, key_hash = generate_invite_key(
        db_url=db_url,
        engram_id=engram_id,
        expires_days=invite_expires_days,
        uses_remaining=invite_uses,
    )

    # Set up schema and workspace row in the database
    if _storage is not None:
        from datetime import timezone
        import time

        expires_ts = datetime.fromtimestamp(
            time.time() + invite_expires_days * 86400, tz=timezone.utc
        ).isoformat()

        await _storage.ensure_workspace(engram_id, anonymous_mode, anon_agents)
        await _storage.insert_invite_key(
            key_hash=key_hash,
            engram_id=engram_id,
            expires_at=expires_ts,
            uses_remaining=invite_uses,
        )

    # Write workspace.json
    config = WorkspaceConfig(
        engram_id=engram_id,
        db_url=db_url,
        schema=schema,
        anonymous_mode=anonymous_mode,
        anon_agents=anon_agents,
        key_generation=0,
        is_creator=True,
    )
    write_workspace(config)
    _write_engram_env(invite_key)
    logger.info(
        "Workspace initialized: %s (schema: %s, anonymous=%s)", engram_id, schema, anonymous_mode
    )

    return {
        "status": "initialized",
        "engram_id": engram_id,
        "schema": schema,
        "invite_key": invite_key,
        "next_prompt": (
            f"Your team workspace is ready.\n\n"
            f"Share this invite link with your teammates — it's all they need:\n\n"
            f"  https://www.engram-memory.com/join?key={invite_key}\n\n"
            f"They click the link, sign in, and accept the invite. No installation, "
            f"no configuration. When they open this codebase, their agent connects "
            f"automatically using the .engram.env file now in your repo.\n\n"
            f"By accepting the invite, teammates agree that their agent's messages "
            f"will be recorded as facts in the shared workspace — this is what Engram "
            f"does. They can leave the workspace at any time from the dashboard.\n\n"
            f"Workspace ID: {engram_id}\n\n"
            f"User messages are now captured automatically by IDE-level hooks. "
            f"Use engram_commit to record verified discoveries and decisions."
        ),
    }


# ── engram_join ───────────────────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
async def engram_join(invite_key: str) -> dict[str, Any]:
    """Join an existing Engram workspace using only an Invite Key.

    **Precondition:** You must have a valid invite key from the workspace creator.

    **When to call:**
    - After engram_status prompts you to join a workspace
    - When the workspace creator shares an invite key with you

    **What NOT to do:**
    - Don't call this if you're creating a new workspace — use engram_init instead
    - Don't share invite keys publicly — they contain encrypted database credentials
    - Don't use expired or revoked keys — request a new one from the creator

    **Common mistake:** Trying to join before getting a valid invite key. Ask the
    workspace creator for their invite key first.

    The invite key contains everything needed — the database URL and
    workspace ID are encrypted inside it. No Team ID required.

    Parameters:
    - invite_key: The invite key shared by the workspace founder (e.g. ek_live_...).

    Returns: {status, engram_id, schema, next_prompt}

    Example: {"status": "ready", "engram_id": "ENG-XXXXXX", "schema": "engram"}
    """
    result = await _join_workspace(invite_key)
    if result["status"] != "joined":
        return result

    return {
        **result,
        "next_prompt": (
            "Connected. Your agent now has access to the team's shared memory.\n\n"
            "User messages are captured automatically by IDE-level hooks. "
            "Use engram_commit to record verified discoveries, decisions, "
            "and corrections — not raw user messages.\n\n"
            "Before starting any task, call engram_query to check what the "
            "team already knows."
        ),
    }


# ── engram_rename ────────────────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
async def engram_rename(
    display_name: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Set or update the workspace display name and description (issue #64).

    Workspaces are identified by UUID (engram_id). This tool allows setting
    a human-readable name like "Acme Payments Team" and optional description.

    Parameters:
    - display_name: Human-readable workspace name (e.g., "Engineering Team").
      Set to empty string to clear.
    - description: Optional description of the workspace purpose.

    Returns: {status, display_name, description, next_prompt}

    Example: {"status": "updated", "display_name": "Engineering Team"}
    """
    from engram.workspace import read_workspace, set_workspace_setting

    ws = read_workspace()
    if ws is None:
        return {
            "status": "error",
            "next_prompt": "No workspace configured. Run engram init or engram join first.",
        }

    errors = []
    if "display_name" in (ws and str(ws)) or display_name:
        try:
            set_workspace_setting("display_name", display_name)
        except ValueError as e:
            errors.append(str(e))

    if description:
        try:
            set_workspace_setting("description", description)
        except ValueError as e:
            errors.append(str(e))

    if errors:
        return {
            "status": "error",
            "next_prompt": f"Failed to update workspace: {'; '.join(errors)}",
        }

    updated = read_workspace()
    return {
        "status": "updated",
        "display_name": updated.display_name if updated else display_name,
        "description": updated.description if updated else description,
        "next_prompt": (
            f"Workspace updated: {display_name or '(unnamed)'}\n"
            f"Description: {description or 'None'}"
        ),
    }


# ── engram_reset_invite_key ──────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
async def engram_reset_invite_key(
    invite_expires_days: int = 90,
    invite_uses: int = 10,
    grace_minutes: int = 15,
    reason: str = "",
) -> dict[str, Any]:
    """Reset the workspace invite key (workspace creator only).

    **Precondition:** You must be the workspace creator (is_creator=true in workspace.json).

    **When to call:**
    - When you suspect a security breach or compromised key
    - When you need to revoke access for a former team member
    - As part of periodic security rotation (recommended: quarterly)

    **What NOT to do:**
    - Don't call this without reason — all team members will eventually be disconnected
    - Don't call this if you're not the workspace creator — you'll get an error
    - Don't forget to share the new key with your team after resetting

    **Common mistake:** Forgetting to share the new invite key with team members after
    resetting, leaving them unable to reconnect after the grace period ends.

    Use this when you suspect a security breach or the current invite key
    has been compromised. This will:
      1. Soft-revoke all existing invite keys (with a grace period for active sessions).
      2. Increment the workspace key generation counter.
      3. Generate a new invite key.
      4. Write an audit log entry and fire a webhook event.

    Existing members in active sessions continue working until grace_minutes expires.
    New join attempts with the old key are rejected immediately regardless of grace.
    After the grace window, existing members see a reconnect message.

    This tool is only available to the workspace creator (the agent that
    originally called engram_init). Other agents will receive an error.

    Parameters:
    - invite_expires_days: Validity period for the new key (default 90 days).
    - invite_uses: Max number of times the new key can be used (default 10).
    - grace_minutes: Grace window in minutes for active sessions (default 15, 0 = immediate).
    - reason: Optional note explaining why the key was rotated (stored in audit log).

    Returns: {status, invite_key, key_generation, grace_until, next_prompt}

    Example: {"status": "reset", "invite_key": "ek_live_...", "key_generation": 2}
    """
    if _engine is None:
        return {
            "status": "error",
            "next_prompt": "Storage not initialized. Restart the Engram server and try again.",
        }

    try:
        result = await _engine.rotate_invite_key(
            expires_days=invite_expires_days,
            uses=invite_uses,
            grace_minutes=grace_minutes,
            reason=reason or None,
            actor=None,
        )
    except ValueError as exc:
        return {"status": "error", "next_prompt": str(exc)}
    except PermissionError as exc:
        return {"status": "error", "next_prompt": str(exc)}

    invite_key = result["invite_key"]
    new_gen = result["new_generation"]
    grace_until = result.get("grace_until")
    grace_note = (
        f"\n\nActive sessions have a {grace_minutes}-minute grace period (until {grace_until}) "
        f"before they are disconnected."
        if grace_until
        else "\n\nAll existing sessions have been disconnected immediately."
    )

    return {
        "status": "reset",
        "invite_key": invite_key,
        "key_generation": new_gen,
        "grace_until": grace_until,
        "next_prompt": (
            f"Security reset complete. All existing invite keys have been revoked.{grace_note}\n\n"
            f"Key generation is now {new_gen}. Members will see a message asking them to reconnect "
            f"once the grace period ends.\n\n"
            f"Share this new invite key with your team via a secure channel "
            f"(iMessage, WhatsApp, Slack DM, etc.):\n\n"
            f"  Invite Key: {invite_key}\n\n"
            f"Members rejoin by calling engram_join with this key, then restarting "
            f"their MCP client. This key can be used {invite_uses} times and expires "
            f"in {invite_expires_days} days."
        ),
    }


# ── engram_commit ────────────────────────────────────────────────────


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
async def engram_commit(
    content: str,
    scope: str = "general",
    confidence: float = 0.8,
    agent_id: str | None = None,
    engineer: str | None = None,
    corrects_lineage: str | None = None,
    provenance: str | None = None,
    fact_type: str = "observation",
    ttl_days: int | None = None,
    operation: str = "add",
    durability: str = "durable",
) -> dict[str, Any]:
    """Record a verified discovery, decision, or correction to shared team memory.

    Use this when your agent discovers something worth preserving — not for
    raw user messages (those are captured automatically by IDE-level hooks).

    **Precondition:** Call engram_status first to ensure workspace is ready.

    **When to call:**
    - After discovering something worth preserving (side effects, failures, constraints)
    - When making architectural decisions
    - After tests reveal behavior not documented elsewhere
    - To correct an outdated fact (use operation="update")

    **What NOT to do:**
    - Don't commit speculative claims — only verified discoveries
    - Don't commit secrets, API keys, or credentials (will be rejected)
    - Don't call more than 5 times per task; batch related facts

    **Common mistake:** Forgetting to commit discoveries, leaving the next
    agent to re-discover the same information.

    Use this when your agent discovers something worth preserving:
    a hidden side effect, a failed approach, an undocumented constraint,
    an architectural decision, or a configuration detail.

    IMPORTANT: Do not commit speculative or uncertain claims. Only commit
    facts your agent has verified through code reading, testing, or
    direct observation. Set confidence below 0.5 for uncertain claims.

    IMPORTANT: Do not include secrets, API keys, passwords, or credentials
    in the content field. The server will reject commits containing
    detected secrets.

    IMPORTANT: Do not call this tool more than 5 times per task. Batch
    related discoveries into a single, well-structured claim.

    Parameters:
    - content: The claim in plain English. Be specific. Include service
      names, version numbers, config keys, and numeric values where
      relevant. BAD: "auth is broken". GOOD: "The auth service
      rate-limits to 1000 req/s per IP using a sliding window in Redis,
      configured via AUTH_RATE_LIMIT in .env".
    - scope: Hierarchical topic path. Defaults to "general". Examples:
      "auth", "payments/webhooks", "infra/docker". Use consistent scopes
      across your team.
    - confidence: 0.0-1.0. Defaults to 0.8. How certain is this claim?
      1.0 = verified in code. 0.7 = observed behavior. 0.3 = inferred
      from context.
    - agent_id: Your agent identifier. Use your agent name for attribution
      (e.g. the name field from your AgentConfig when using open-multi-agent).
      Auto-generated if omitted.
    - engineer: Optional human identifier (email or username) of the engineer
      whose agent is making this commit. Used for team attribution and trust
      scoring. Example: "alice@example.com" or your GitHub username.
    - corrects_lineage: If this claim corrects a previous one, pass the
      lineage_id of the claim being corrected. The old claim will be
      marked as superseded.
    - provenance: Optional evidence trail. File path, line number, test
      output, or tool call ID that generated this evidence. Facts with
      provenance are marked as verified in query results.
    - fact_type: "observation" (directly observed in code/tests/logs),
      "inference" (concluded from observations), or "decision"
      (architectural decision by humans or agents). Default: observation.
    - ttl_days: Optional time-to-live in days. When set, the fact
      automatically expires after this period. Useful for facts about
      external dependencies, API contracts, or infrastructure that
      change frequently. Default: null (no expiry).
    - operation: Memory CRUD intent. One of:
        "add"    (default) — new independent fact.
        "update" — supersede an outdated fact. If corrects_lineage is
                   omitted, the engine automatically finds the most
                   semantically similar active fact in scope and supersedes
                   it (no lineage tracking required from the caller).
        "delete" — retire an existing fact without replacement; requires
                   corrects_lineage (the lineage_id to close).
        "none"   — no-op; signals the agent has nothing new to add.
    - durability: Memory tier. One of:
        "durable"   (default) — persistent fact. Included in queries by
                     default. Triggers conflict detection. Use for verified
                     discoveries that the team should know about.
        "ephemeral" — scratchpad memory. Excluded from queries unless
                     include_ephemeral=true is passed. Skips conflict
                     detection. Auto-expires after ttl_days (default 1 day).
                     Automatically promoted to durable when queried at least
                     twice. Use for in-progress observations, hypotheses,
                     or context that hasn't proven its value yet.

    Returns: {fact_id, committed_at, duplicate, conflicts_detected,
              memory_op, supersedes_fact_id, durability, suggestions}

    Example: {"fact_id": "fact_xyz789", "committed_at": "2026-04-10T15:30:00Z", "duplicate": false, "conflicts_detected": 0}
    """
    engine = get_engine()

    # Key generation check — block disconnected agents
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc

    # Rate limiting (Phase 5)
    effective_agent = agent_id or "anonymous"
    if _rate_limiter is not None:
        if not _rate_limiter.check(effective_agent):
            raise ValueError(
                f"Rate limit exceeded for agent '{effective_agent}'. "
                f"Max {_rate_limiter.max_per_hour} commits per hour."
            )

    # Scope permission check (Phase 5)
    if _storage is not None and agent_id:
        from engram.auth import check_scope_permission

        allowed = await check_scope_permission(_storage, agent_id, scope, "write")
        if not allowed:
            raise ValueError(
                f"Agent '{agent_id}' does not have write permission for scope '{scope}'."
            )

    result = await engine.commit(
        content=content,
        scope=scope,
        confidence=confidence,
        agent_id=agent_id,
        engineer=engineer,
        corrects_lineage=corrects_lineage,
        provenance=provenance,
        fact_type=fact_type,
        ttl_days=ttl_days,
        operation=operation,
        durability=durability,
    )

    # Record rate limit usage after successful commit
    if _rate_limiter is not None:
        _rate_limiter.record(effective_agent)

    return result


# ── engram_query ─────────────────────────────────────────────────────


@mcp.tool(
    annotations={"readOnlyHint": True},
)
async def engram_query(
    topic: str,
    scope: str | None = None,
    limit: int = 10,
    as_of: str | None = None,
    fact_type: str | None = None,
    agent_id: str | None = None,
    include_ephemeral: bool = False,
    include_adjacent: bool = False,
    include_history: bool = False,
) -> list[dict[str, Any]]:
    """Query what your team's agents collectively know about a topic.

    **Precondition:** Call engram_status first to ensure workspace is ready.

    **When to call:**
    - BEFORE starting any task or feature work
    - When you encounter an error and need context
    - Before making architectural decisions

    **What NOT to do:**
    - Don't call this AFTER you've already started working — you wasted context
    - Don't make multiple broad queries; be specific with your topic
    - Don't treat disputed claims (has_open_conflict=true) as settled facts

    **Common mistake:** Starting work without engram_query, then rediscovering
    what another agent already documented.

    Parameters:
    - topic: What you want to know about. Be specific. BAD: "auth".
      GOOD: "How does the auth service handle JWT token refresh?"
    - scope: Optional filter. "auth" returns claims in "auth" and all
      sub-scopes like "auth/jwt", "auth/oauth".
    - limit: Max results (default 10, max 50).
    - as_of: ISO 8601 timestamp for historical queries. Returns what
      the system knew at that point in time.
    - fact_type: Optional filter. "observation", "inference", or
      "decision". Omit to return all types.
    - agent_id: Your agent identifier. Used for read permission checks
      when the server runs in auth mode (--auth flag). Match the same
      agent_id you use when calling engram_commit.
    - include_ephemeral: When true, includes ephemeral (scratchpad) facts
      alongside durable facts. Ephemeral facts are short-lived observations
      that haven't proven their value yet. They rank lower than durable
      facts. Ephemeral facts that appear in query results are tracked;
      once queried twice they are automatically promoted to durable.
      Default: false.
    - include_adjacent: When true and a scope is provided, also searches
      sibling and parent scopes for semantically related facts. Adjacent
      results are marked with adjacent=true and include their original_scope
      so you can distinguish in-scope from related knowledge. Useful when
      a query might benefit from cross-cutting context. Default: false.
    - include_history: When true, each returned fact includes a `history`
      array showing all prior versions in its lineage — oldest first. Each
      history entry has content, committed_at, agent_id, fact_type,
      confidence, and superseded. Use this to understand how knowledge
      evolved over time, e.g. to detect reversals or see who changed what.
      Default: false.

    Returns: List of claims with content, scope, confidence, agent_id,
    committed_at, has_open_conflict, verified, fact_type, durability,
    adjacent, and provenance metadata.

    Example return:
    [
      {
        "id": "fact_abc123",
        "content": "The auth service rate-limits to 1000 req/s per IP using Redis",
        "scope": "auth",
        "confidence": 0.95,
        "agent_id": "claude-code",
        "committed_at": "2026-04-10T15:30:00Z",
        "has_open_conflict": false,
        "verified": true,
        "fact_type": "observation"
      }
    ]
    """
    engine = get_engine()

    # Key generation check — block disconnected agents
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc

    # Query loop detection (Issue #66)
    # Track queries per agent to detect repeated queries without new results
    effective_agent = agent_id or "anonymous"
    topic_key = topic.lower().strip()

    # Initialize agent's query history if needed
    if effective_agent not in _query_history:
        _query_history[effective_agent] = []

    # Count how many times this topic has been queried
    topic_count = _query_history[effective_agent].count(topic_key)
    _query_history[effective_agent].append(topic_key)

    # Log warning if query repeated 3+ times
    if topic_count >= 2:  # 3rd+ time
        logger.warning(
            f"Query loop detected: agent '{effective_agent}' queried topic '{topic}' "
            f"{topic_count + 1} times this session with no new commits. "
            "Consider committing findings or reframing the question."
        )

    # Scope read permission check when auth is enabled and scope is specified
    if _auth_enabled and _storage is not None and agent_id and scope:
        from engram.auth import check_scope_permission

        allowed = await check_scope_permission(_storage, agent_id, scope, "read")
        if not allowed:
            raise ValueError(
                f"Agent '{agent_id}' does not have read permission for scope '{scope}'."
            )

    return await engine.query(
        topic=topic,
        scope=scope,
        limit=limit,
        as_of=as_of,
        fact_type=fact_type,
        include_ephemeral=include_ephemeral,
        include_adjacent=include_adjacent,
        include_history=include_history,
    )


# ── engram_conflicts ─────────────────────────────────────────────────


@mcp.tool(
    annotations={"readOnlyHint": True},
)
async def engram_conflicts(
    scope: str | None = None,
    status: str = "open",
) -> list[dict[str, Any]]:
    """See where agents disagree about the codebase.

    **When to call:**
    - Before making architectural decisions
    - When setting up a new service or feature
    - After any major refactoring that might affect shared contracts

    **What NOT to do:**
    - Don't ignore conflicts — they indicate the team has contradictory beliefs
    - Don't rely on claims with has_open_conflict=true without resolving them

    **Common mistake:** Making decisions without checking conflicts first, leading
    to conflicting implementations by different team members.

    Returns pairs of claims that contradict each other. Each conflict
    includes both claims, the detection method, severity, and an
    explanation (when available).

    Review these before making architectural decisions. A conflict means
    two agents (possibly from different engineers) believe incompatible
    things about the same system.

    Parameters:
    - scope: Optional filter by scope prefix.
    - status: "open" (default), "resolved", "dismissed", or "all".

    Returns: List of conflicts with claim pairs, severity, detection
    method, and resolution status.

    Example return:
    [
      {
        "id": "conflict_123",
        "severity": "medium",
        "status": "open",
        "fact_a": {"content": "Auth uses JWT with 1h expiry", "scope": "auth", "agent_id": "agent1"},
        "fact_b": {"content": "Auth uses JWT with 24h expiry", "scope": "auth", "agent_id": "agent2"}
      }
    ]
    """
    engine = get_engine()
    return await engine.get_conflicts(scope=scope, status=status)


# ── engram_resolve ───────────────────────────────────────────────────


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    },
)
async def engram_resolve(
    conflict_id: str,
    resolution_type: str,
    resolution: str,
    winning_claim_id: str | None = None,
    winning_fact_id: str | None = None,
) -> dict[str, Any]:
    """Settle a disagreement between claims.

    **Precondition:** Call engram_conflicts first to see the conflict you want to resolve.

    **When to call:**
    - After reviewing a conflict and determining which claim is correct
    - When two claims are both partially correct and you want to merge them
    - When a detected conflict is actually a false positive

    **What NOT to do:**
    - Don't resolve without reviewing both claims — you might pick the wrong one
    - Don't use "winner" without specifying winning_claim_id
    - Don't ignore conflicts — they indicate contradictory team beliefs

    **Common mistake:** Resolving conflicts without reading both claims carefully. Always
    review the actual content before deciding which is correct.

    Three resolution types:
    - "winner": One claim is correct. Pass winning_claim_id. The losing
      claim is marked superseded.
    - "merge": Both claims are partially correct. Commit a new merged
      claim first, then resolve with this tool.
    - "dismissed": The conflict is a false positive (claims don't actually
      contradict). This feedback improves future detection accuracy.

    Parameters:
    - conflict_id: The conflict to resolve.
    - resolution_type: "winner", "merge", or "dismissed".
    - resolution: Human-readable explanation of why this resolution
      is correct.
    - winning_claim_id: Required when resolution_type is "winner".

    Returns: {resolved: true, conflict_id, resolution_type}

    Example: {"resolved": true, "conflict_id": "conflict_123", "resolution_type": "winner"}
    """
    engine = get_engine()

    warnings: list[dict[str, str]] = []

    if winning_claim_id is not None and winning_fact_id is not None:
        raise ValueError(
            "Provide only one of 'winning_claim_id' or deprecated alias 'winning_fact_id'."
        )

    if winning_fact_id is not None:
        warning = deprecation_warning("engram_resolve", "winning_fact_id")
        if warning:
            warnings.append(warning)
        winning_claim_id = winning_fact_id

    result = await engine.resolve(
        conflict_id=conflict_id,
        resolution_type=resolution_type,
        resolution=resolution,
        winning_claim_id=winning_claim_id,
    )

    result.update(tool_surface_metadata())
    if warnings:
        result["deprecation_warnings"] = warnings

    return result


# ── engram_batch_commit ──────────────────────────────────────────────


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
async def engram_batch_commit(
    facts: list[dict[str, Any]],
    agent_id: str | None = None,
    engineer: str | None = None,
) -> dict[str, Any]:
    """Commit multiple facts to shared team memory in a single call.

    Use this to bootstrap knowledge from wikis, runbooks, ADRs, or any
    structured source — rather than making dozens of individual engram_commit
    calls.  Each fact goes through the same full pipeline as engram_commit
    (dedup, secret scan, embedding, conflict detection), so no quality is
    lost by batching.

    A validation or secret-scan failure on one fact does NOT abort the batch.
    Inspect the per-fact "status" in the results list to see what happened.

    Parameters:
    - facts: List of fact objects.  Each object may include:
        - content (required): The claim in plain English.
        - scope (required): Hierarchical topic path, e.g. "auth/jwt".
        - confidence (required): 0.0–1.0.
        - fact_type: "observation" | "inference" | "decision". Default: observation.
        - agent_id: Overrides the top-level agent_id for this specific fact.
        - engineer: Overrides the top-level engineer for this specific fact.
        - provenance: Evidence trail (file path, test output, etc.).
        - ttl_days: Optional TTL in days.
        - operation: "add" | "update" | "delete" | "none". Default: add.
        - durability: "durable" | "ephemeral". Default: durable.
        - corrects_lineage: lineage_id to supersede (for update/delete ops).
    - agent_id: Default agent_id applied to all facts that omit it.
    - engineer: Default engineer applied to all facts that omit it.

    Returns:
    {
      total: int,          # number of facts submitted
      committed: int,      # successfully written (not duplicates)
      duplicates: int,     # already existed — no-op
      failed: int,         # validation or secret-scan errors
      results: [           # per-fact outcome, preserving input order
        {index, status: "ok"|"duplicate"|"error", fact_id?, error?}
      ]
    }

    Example: {"total": 5, "committed": 4, "duplicates": 0, "failed": 1, "results": [{"index": 0, "status": "ok", "fact_id": "fact_123"}, {"index": 1, "status": "error", "error": "Secret detected: Email Address"}]}

    Limits: Maximum 100 facts per batch.
    """
    engine = get_engine()

    # Key generation check
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc

    return await engine.batch_commit(
        facts=facts,
        default_agent_id=agent_id,
        default_engineer=engineer,
    )


# ── engram_promote ───────────────────────────────────────────────────


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    },
)
async def engram_promote(fact_id: str) -> dict[str, Any]:
    """Promote an ephemeral fact to durable persistent memory.

    Use this when an ephemeral observation has proven its value and should
    become part of the team's persistent knowledge base. Promotion makes
    the fact visible in default queries and enables conflict detection.

    IMPORTANT: Only promote facts you're confident are valuable. Promotion
    signals to the team that this knowledge is trustworthy and worth
    remembering permanently.

    IMPORTANT: To get fact_id, query with include_ephemeral=true. Ephemeral
    facts in query results include their fact_id field. You can then pass
    that ID here to promote it.

    Ephemeral facts are also auto-promoted when they appear in query
    results at least twice (the "proved useful more than once" heuristic),
    so explicit promotion is only needed when you want to fast-track a
    fact you know is valuable immediately.

    Example workflow:
    1. Query with include_ephemeral=true to find relevant ephemeral facts
    2. Review the facts and determine which are valuable enough to promote
    3. Call engram_promote with the fact_id of each valuable fact

    Parameters:
    - fact_id: The ID of the ephemeral fact to promote. Get this from
      query results (include_ephemeral=true returns fact_id for each fact).

    Returns: {promoted: true, fact_id, durability: "durable"}
    """
    engine = get_engine()
    return await engine.promote(fact_id=fact_id)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    },
)
async def engram_feedback(
    conflict_id: str,
    feedback: str,
) -> dict[str, Any]:
    """Record human feedback on a conflict detection to improve accuracy.

    Call this after reviewing a conflict to label it as a real contradiction
    (true_positive) or a false alarm (false_positive). Feedback is aggregated
    in workspace statistics and can be used to tune detection thresholds.

    Parameters:
    - conflict_id: The ID of the conflict to annotate.
    - feedback: 'true_positive' (real conflict) or 'false_positive' (false alarm).

    Returns: {recorded: true, conflict_id, feedback}
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.record_feedback(conflict_id=conflict_id, feedback=feedback)


@mcp.tool(annotations={"readOnlyHint": True})
async def engram_timeline(
    scope: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return the chronological fact history for audit and debugging.

    Useful for understanding how shared knowledge in a scope has evolved over
    time, reviewing what was committed and when, and spotting lineage chains.

    Parameters:
    - scope: Optional scope prefix to filter (e.g. 'auth', 'infra').
    - limit: Max facts to return (1–200, default 50).

    Returns: List of fact summaries ordered by valid_from ascending.
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.get_timeline(scope=scope, limit=limit)


@mcp.tool(annotations={"readOnlyHint": True})
async def engram_stats() -> dict[str, Any]:
    """Return privacy-preserving aggregate workspace analytics.

    Use this to understand workspace health without exposing memory content:
    fact counts, safe most-queried fact metadata, conflict rate and daily
    conflict buckets, active agents, and detection feedback totals.

    Returns: Aggregate statistics only; no fact content is included.
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.get_stats()


@mcp.tool(annotations={"readOnlyHint": True})
async def engram_audit_trail(
    agent_id: str | None = None,
    operation: str | None = None,
    from_timestamp: str | None = None,
    to_timestamp: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query the workspace audit trail for tracking agent activities.

    Returns a chronological record of all operations performed in the workspace,
    including commits, resolutions, imports, and other actions. Useful for
    auditing what changes were made, when, and by whom.

    Parameters:
    - agent_id: Optional filter by specific agent (e.g. 'agent-1').
    - operation: Optional filter by operation type ('commit', 'resolve', 'import', etc).
    - from_timestamp: Filter entries after this ISO timestamp.
    - to_timestamp: Filter entries before this ISO timestamp.
    - limit: Max entries to return (1-1000, default 100).

    Returns: List of audit log entries with timestamps, operations, and details.
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.get_audit_log(
        agent_id=agent_id,
        operation=operation,
        from_ts=from_timestamp,
        to_ts=to_timestamp,
        limit=limit,
    )


@mcp.tool(annotations={"readOnlyHint": True})
async def engram_agents() -> list[dict[str, Any]]:
    """List all registered agents and their activity statistics.

    Returns each agent's commit count, flagged count, engineer association,
    and last-seen timestamp. Useful for auditing which agents are active
    and identifying agents with high flag rates.

    Returns: List of agent records ordered by last_seen descending.
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.get_agents()


@mcp.tool(annotations={"readOnlyHint": True})
async def engram_lineage(lineage_id: str) -> list[dict[str, Any]]:
    """Return the full version history of a fact lineage.

    Every time a fact is corrected or updated via corrects_lineage, a new
    version is appended to the same lineage. This tool shows all versions
    ordered newest-first so you can trace how a piece of knowledge evolved.

    Parameters:
    - lineage_id: The lineage UUID to look up (from any fact's lineage_id field).

    Returns: List of fact dicts (newest first). Empty if lineage not found.
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.get_lineage(lineage_id)


@mcp.tool(annotations={"readOnlyHint": True})
async def engram_expiring(days_ahead: int = 7) -> list[dict[str, Any]]:
    """Return facts whose TTL will expire within the next N days.

    Call this periodically to proactively refresh knowledge before it expires.
    Facts listed here have a valid_until set and will become invisible to
    normal queries once that timestamp passes.

    Parameters:
    - days_ahead: Look-ahead window in days (1–30, default 7).

    Returns: List of expiring facts ordered by valid_until ascending (soonest first).
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.get_expiring_facts(days_ahead=days_ahead)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    },
)
async def engram_bulk_dismiss(
    conflict_ids: list[str],
    reason: str,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Dismiss multiple open conflicts in one call.

    Use after reviewing a batch of false-positive detections, or after a
    large refactor that makes many existing conflicts obsolete. Each conflict
    is dismissed individually — a failure on one does not abort the rest.

    Parameters:
    - conflict_ids: List of conflict IDs to dismiss (max 100).
    - reason: Human-readable explanation recorded on each conflict.
    - agent_id: Optional agent performing the dismissal (for audit trail).

    Returns: {total, dismissed, failed, results: [{conflict_id, status, error?}]}
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.bulk_dismiss(
        conflict_ids=conflict_ids,
        reason=reason,
        dismissed_by=agent_id,
    )


@mcp.tool(annotations={"readOnlyHint": True})
async def engram_export(
    format: Literal["json", "markdown"] = "json",
    scope: str | None = None,
) -> dict[str, Any]:
    """Export workspace as a portable JSON or Markdown snapshot.

    Use this to create backups, share knowledge with non-Engram users,
    or migrate data to another workspace.

    JSON format produces a machine-readable document suitable for backup,
    migration, or tooling integration. It includes all current facts,
    conflicts, and metadata.

    Markdown format produces a human-readable document grouped by scope.
    Paste it into Confluence, a PR description, or an onboarding doc.

    IMPORTANT: This is a read-only operation — it does not modify your
    workspace. Both durable and ephemeral facts are included.

    IMPORTANT: If secrets are detected in fact content, they are
    automatically redacted and a warning is added to the metadata.

    Parameters:
    - format: Output format — "json" or "markdown".
    - scope: Optional scope prefix filter (e.g., "auth" returns facts
      in "auth", "auth/jwt", "auth/oauth", etc.).

    Returns: Export document with metadata, facts, and conflicts.
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    if not _ws:
        return {"error": "Workspace not initialized. Run engram_init first."}
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc

    if format not in ("json", "markdown"):
        return {"error": f"Invalid format '{format}'. Supported: json, markdown"}

    try:
        return await engine.export_workspace(format=format, scope=scope)
    except Exception as exc:
        logger.exception("engram_export error")
        return {"error": str(exc)}


# ── engram_gdpr_erase ─────────────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
async def engram_gdpr_erase(
    agent_id: str,
    mode: Literal["soft", "hard"] = "soft",
) -> dict[str, Any]:
    """Erase personal data for an agent (GDPR right-to-erasure). Founder only.

    Use this when a team member leaves and you receive a legal erasure request
    for an EU / GDPR-covered subject.  Always back up your database before
    running a hard erase.

    **soft** — Redacts the engineer name and provenance field on every fact
    version committed by this agent. Conflict explanation strings are scrubbed
    to avoid leaking the name indirectly. Fact content remains intact so the
    team's knowledge base stays coherent.

    **hard** — Everything in soft mode, plus: fact content is replaced with a
    per-row placeholder, keywords, entities, and the embedding vector are
    cleared (so the fact cannot be retrieved by content or semantic search),
    the validity window is closed on all still-current facts (retiring them),
    and every open conflict that references an erased fact is dismissed with
    resolution_type='gdpr_erasure'. This mode is irreversible.

    In both modes the following are also scrubbed:
    - agents table: engineer name and label.
    - scope_permissions (hard only): rows for this agent are deleted.
    - scopes: owner_agent_id nulled where it matched.
    - audit_log: agent_id and associated fact_id references are cleared.

    IMPORTANT: This operation is restricted to the workspace creator (founder).
    IMPORTANT: The anonymous_mode workspace setting is not sufficient for GDPR
    compliance — it prevents future attribution but does not erase historical
    data.  Use this tool for legal right-to-erasure requests instead.

    Parameters:
    - agent_id: The exact agent ID to erase (find it via engram_agents).
    - mode: 'soft' (redact attribution only) or 'hard' (wipe content too).

    Returns: {erased_agent_id, mode, stats: {facts_updated, conflicts_closed, ...}}
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    if not _ws:
        return {"error": "Workspace not initialized. Run engram_init first."}

    try:
        return await engine.gdpr_erase_agent(
            agent_id=agent_id,
            mode=mode,
            actor=None,
        )
    except PermissionError as exc:
        return {"error": str(exc), "status": "forbidden"}
    except ValueError as exc:
        return {"error": str(exc), "status": "invalid_request"}
    except Exception as exc:
        logger.exception("engram_gdpr_erase error")
        return {"error": str(exc)}


# ── engram_create_webhook ─────────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
async def engram_create_webhook(
    url: str,
    events: list[str],
    secret: str | None = None,
) -> dict[str, Any]:
    """Register a webhook URL to receive event notifications.

    Events fired: 'fact.committed', 'conflict.detected', 'conflict.resolved',
    'fact.expired'. Use '*' in events list to subscribe to all.

    Parameters:
    - url: The HTTPS URL to POST event payloads to.
    - events: List of event types to subscribe to.
    - secret: Optional HMAC secret for payload signing (X-Engram-Signature header).

    Returns: {webhook_id, url, events, created_at}
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.create_webhook(url=url, events=events, secret=secret)


# ── engram_create_rule ────────────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
async def engram_create_rule(
    scope_prefix: str,
    condition_type: str,
    condition_value: str,
    resolution_type: str = "winner",
) -> dict[str, Any]:
    """Create an auto-resolution rule for a scope prefix.

    When a conflict is detected in a matching scope, the rule fires and
    automatically resolves the conflict without human intervention.

    Parameters:
    - scope_prefix: Scope prefix to match (e.g. 'auth', 'payments/').
    - condition_type: One of 'latest_wins', 'highest_confidence', 'confidence_delta'.
    - condition_value: For 'confidence_delta', the minimum delta (e.g. '0.2').
      For other types, pass an empty string or '1'.
    - resolution_type: Resolution type to apply (default 'winner').

    Returns: {rule_id, scope_prefix, condition_type, condition_value, resolution_type, created_at}
    """
    engine = get_engine()
    from engram.workspace import read_workspace as _rw

    _ws = _rw()
    _disc = await _check_key_generation(_ws)
    if _disc:
        return _disc
    return await engine.create_rule(
        scope_prefix=scope_prefix,
        condition_type=condition_type,
        condition_value=condition_value,
        resolution_type=resolution_type,
    )


# ── engram_check_conflicts ───────────────────────────────────────────────


@mcp.tool(annotations={"readOnlyHint": True})
async def engram_check_conflicts(
    content: str,
    scope: str | None = None,
) -> dict[str, Any]:
    """Check if proposed content conflicts with existing facts.

    Use this as a pre-commit hook - before writing code or making decisions,
    check if the proposed action contradicts established knowledge.

    Parameters:
    - content: The proposed fact or action to check.
    - scope: Optional scope to filter checks (e.g., 'backend', 'auth').

    Returns: {has_conflicts, conflicts: [{fact_id, explanation, severity}]}
    If has_conflicts is true, the action should be blocked until resolved.
    """
    engine = get_engine()
    if engine is None:
        return {"error": "Engine not initialized"}

    fact = {
        "content": content,
        "scope": scope or "global",
        "confidence": 0.9,
        "fact_type": "observation",
        "agent_id": "pre-commit-hook",
    }

    await engine.commit(fact)
    conflicts = await engine.get_conflicts(scope=fact["scope"], status="open")

    if conflicts:
        return {
            "has_conflicts": True,
            "conflicts": [
                {
                    "conflict_id": c.get("id"),
                    "fact_id": c.get("fact_a_id"),
                    "explanation": c.get("explanation"),
                    "severity": c.get("severity"),
                }
                for c in conflicts[:5]
            ],
            "message": f"Found {len(conflicts)} conflicting facts.",
        }

    return {
        "has_conflicts": False,
        "conflicts": [],
        "message": "No conflicts detected. Safe to proceed.",
    }


@mcp.tool(annotations={"readOnlyHint": False})
async def engram_chat(
    message: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Conversational interface to Engram's active memory.

    Understands context from open conflicts and stored facts. Short inputs
    like "B" are resolved against active conflicts. Maintains conversation
    history for multi-turn exchanges.

    Parameters:
    - message: The user's message.
    - history: Prior turns as [{role: user|assistant, content: str}].

    Returns: {reply: str, action: str | None}
    """
    import os

    engine = get_engine()
    if engine is None:
        return {"error": "Engine not initialized"}

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if not anthropic_key and not openai_key:
        return {
            "error": "No AI API key configured on server. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in your Vercel environment variables."
        }

    # Gather context: open conflicts + relevant memory facts
    conflicts = await engine.get_conflicts(status="open")
    facts = await engine.query(topic=message, limit=8)

    conflicts_text = ""
    if conflicts:
        lines = [f"Open conflicts ({len(conflicts)} total):"]
        for c in conflicts[:5]:
            cid = (c.get("id") or "")[:8]
            exp = c.get("explanation") or "Conflicting information"
            fa = (c.get("fact_a") or {}).get("content") or c.get("fact_a_content") or ""
            fb = (c.get("fact_b") or {}).get("content") or c.get("fact_b_content") or ""
            lines.append(f"  [{cid}] {exp}")
            if fa:
                lines.append(f"    A: {fa[:120]}")
            if fb:
                lines.append(f"    B: {fb[:120]}")
        conflicts_text = "\n".join(lines)

    facts_text = ""
    if facts:
        lines = ["Relevant memory facts:"]
        for f in facts:
            agent = f.get("agent_id") or "agent"
            content = (f.get("content") or "")[:150]
            lines.append(f"  [{agent}] {content}")
        facts_text = "\n".join(lines)

    system = (
        "You are Engram, a shared team memory layer for AI agents. "
        "You respond through a terminal TUI. Be concise and direct — "
        "like Claude Code: 1-3 sentences max, no headers or bullet lists unless asked.\n\n"
        "When the user sends a short or ambiguous message, interpret it in context of "
        "the open conflicts below. For example if there is a conflict 'B or C?' and "
        "the user says 'B', confirm you are resolving it as B and tell them the command "
        "to run (e.g. `resolve <id> keep_a`). If input is truly unclear, ask one short "
        "clarifying question.\n\n"
        "When you resolve or act on something, clearly state what you did.\n\n"
    )
    if conflicts_text:
        system += conflicts_text + "\n\n"
    if facts_text:
        system += facts_text + "\n\n"

    messages: list[dict[str, str]] = list(history or [])
    messages.append({"role": "user", "content": message})

    if anthropic_key:
        try:
            import anthropic
        except ImportError:
            return {"error": "anthropic package not installed on server."}
        client = anthropic.AsyncAnthropic(api_key=anthropic_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=system,
            messages=messages,
        )
        reply = response.content[0].text.strip()
    else:
        try:
            import openai
        except ImportError:
            return {"error": "openai package not installed on server."}
        oa_client = openai.AsyncOpenAI(api_key=openai_key)
        oa_messages = [{"role": "system", "content": system}] + messages
        oa_response = await oa_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=256,
            messages=oa_messages,
        )
        reply = (oa_response.choices[0].message.content or "").strip()

    return {"reply": reply}
