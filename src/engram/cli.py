"""CLI entry point for Engram.

Usage:
    engram install                  # auto-detect MCP clients and add Engram config
    engram serve                    # stdio (default, for MCP clients)
    engram serve --http             # Streamable HTTP on localhost:7474
    engram serve --http --auth      # team mode with JWT auth
    engram token create --engineer alice@example.com
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import click

from engram.storage import DEFAULT_DB_PATH


@click.group()
def main() -> None:
    """Engram - Multi-agent memory consistency for engineering teams."""
    pass


# ── engram install ───────────────────────────────────────────────────


# Known MCP client config locations and the JSON path to mcpServers.
# Comprehensive list covering all known MCP-compatible IDEs, editors, CLI
# tools, and desktop apps that store their config in a discoverable file.
# Entries are grouped by category for readability.

import platform as _platform

def _xdg_config() -> Path:
    """Return XDG_CONFIG_HOME or its default."""
    import os
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

def _app_support() -> Path:
    """macOS ~/Library/Application Support."""
    return Path.home() / "Library" / "Application Support"

def _appdata() -> Path:
    """Windows %APPDATA% (falls back to ~/.config on non-Windows)."""
    import os
    return Path(os.environ.get("APPDATA", Path.home() / ".config"))

_IS_MAC = _platform.system() == "Darwin"
_IS_WIN = _platform.system() == "Windows"

_MCP_CLIENTS: dict[str, dict] = {
    # ── Anthropic ────────────────────────────────────────────────────
    "Claude Code": {
        "path": Path.home() / ".claude" / "settings.json",
        "key": "mcpServers",
    },
    "Claude Desktop": {
        "path": (
            _app_support() / "Claude" / "claude_desktop_config.json"
            if _IS_MAC
            else _appdata() / "Claude" / "claude_desktop_config.json"
        ),
        "key": "mcpServers",
    },

    # ── VS Code family ──────────────────────────────────────────────
    "VS Code (Copilot)": {
        "path": Path.home() / ".vscode" / "mcp.json",
        "key": "mcpServers",
    },
    "VS Code Insiders (Copilot)": {
        "path": Path.home() / ".vscode-insiders" / "mcp.json",
        "key": "mcpServers",
    },
    "Cline (VS Code)": {
        "path": Path.home() / ".vscode" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
        "key": "mcpServers",
    },
    "Cline (VS Code Insiders)": {
        "path": Path.home() / ".vscode-insiders" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
        "key": "mcpServers",
    },
    "Roo Code (VS Code)": {
        "path": Path.home() / ".vscode" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
        "key": "mcpServers",
    },
    "Roo Code (VS Code Insiders)": {
        "path": Path.home() / ".vscode-insiders" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
        "key": "mcpServers",
    },
    "Continue (VS Code)": {
        "path": Path.home() / ".continue" / "config.json",
        "key": "mcpServers",
    },
    "Sourcegraph Cody": {
        "path": _xdg_config() / "cody" / "mcp_servers.json",
        "key": "mcpServers",
    },

    # ── AI-native editors ───────────────────────────────────────────
    "Cursor": {
        "path": Path.home() / ".cursor" / "mcp.json",
        "key": "mcpServers",
    },
    "Windsurf": {
        "path": Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
        "key": "mcpServers",
    },
    "Trae": {
        "path": Path.home() / ".trae" / "mcp.json",
        "key": "mcpServers",
    },
    "Zed": {
        "path": _xdg_config() / "zed" / "settings.json",
        "key": "context_servers",  # Zed uses context_servers, not mcpServers
    },
    "Augment Code": {
        "path": Path.home() / ".augment" / "mcp.json",
        "key": "mcpServers",
    },

    # ── Kiro (Amazon) ───────────────────────────────────────────────
    "Kiro": {
        "path": Path.home() / ".kiro" / "settings" / "mcp.json",
        "key": "mcpServers",
    },

    # ── JetBrains IDEs (shared config location) ─────────────────────
    "IntelliJ IDEA": {
        "path": Path.home() / ".idea" / "mcp.json",
        "key": "mcpServers",
    },

    # ── CLI agents ──────────────────────────────────────────────────
    "Codex": {
        "path": Path.home() / ".codex" / "config.toml",
        "key": "mcp_servers",  # TOML format
        "format": "toml",
    },
    "Amazon Q Developer CLI": {
        "path": Path.home() / ".aws" / "amazonq" / "mcp.json",
        "key": "mcpServers",
    },
    "GitHub Copilot CLI": {
        "path": Path.home() / ".copilot" / "mcp-config.json",
        "key": "mcpServers",
    },
    "Gemini CLI": {
        "path": Path.home() / ".gemini" / "settings.json",
        "key": "mcpServers",
    },
    "OpenCode": {
        "path": _xdg_config() / "opencode" / "opencode.json",
        "key": "mcp",
    },
    "Devin CLI": {
        "path": _xdg_config() / "devin" / "config.json",
        "key": "mcpServers",
    },
    "Qwen Code": {
        "path": Path.home() / ".qwen-code" / "settings.json",
        "key": "mcpServers",
    },

    # ── Desktop chat apps ───────────────────────────────────────────
    "Cherry Studio": {
        "path": (
            _app_support() / "CherryStudio" / "mcp.json"
            if _IS_MAC
            else _appdata() / "CherryStudio" / "mcp.json"
        ),
        "key": "mcpServers",
    },
    "ChatBox": {
        "path": (
            _app_support() / "xyz.chatboxapp.app" / "mcp.json"
            if _IS_MAC
            else _appdata() / "xyz.chatboxapp.app" / "mcp.json"
        ),
        "key": "mcpServers",
    },
    "msty": {
        "path": (
            _app_support() / "msty" / "mcp_config.json"
            if _IS_MAC
            else _appdata() / "msty" / "mcp_config.json"
        ),
        "key": "mcpServers",
    },
    "Dive": {
        "path": (
            _app_support() / "Dive" / "mcp_config.json"
            if _IS_MAC
            else _appdata() / "Dive" / "mcp_config.json"
        ),
        "key": "mcpServers",
    },
    "HyperChat": {
        "path": (
            _app_support() / "HyperChat" / "mcp_config.json"
            if _IS_MAC
            else _appdata() / "HyperChat" / "mcp_config.json"
        ),
        "key": "mcpServers",
    },
    "BoltAI": {
        "path": (
            _app_support() / "BoltAI" / "mcp_config.json"
            if _IS_MAC
            else _appdata() / "BoltAI" / "mcp_config.json"
        ),
        "key": "mcpServers",
    },
    "5ire": {
        "path": (
            _app_support() / "5ire" / "mcp_config.json"
            if _IS_MAC
            else _appdata() / "5ire" / "mcp_config.json"
        ),
        "key": "mcpServers",
    },

    # ── Neovim / Emacs ──────────────────────────────────────────────
    "Neovim (mcphub.nvim)": {
        "path": _xdg_config() / "mcphub" / "servers.json",
        "key": "mcpServers",
    },
    "Emacs (mcp.el)": {
        "path": Path.home() / ".emacs.d" / "mcp.json",
        "key": "mcpServers",
    },

    # ── Terminal / Warp ─────────────────────────────────────────────
    "Warp": {
        "path": Path.home() / ".warp" / "mcp.json",
        "key": "mcpServers",
    },

    # ── Theia IDE ───────────────────────────────────────────────────
    "Theia IDE": {
        "path": Path.home() / ".theia" / "mcp.json",
        "key": "mcpServers",
    },

    # ── Refact.ai ───────────────────────────────────────────────────
    "Refact.ai": {
        "path": Path.home() / ".refact" / "mcp.json",
        "key": "mcpServers",
    },

    # ── Aider ───────────────────────────────────────────────────────
    "Aider": {
        "path": Path.home() / ".aider" / "mcp.json",
        "key": "mcpServers",
    },

    # ── Highlight AI ────────────────────────────────────────────────
    "Highlight AI": {
        "path": (
            _app_support() / "Highlight" / "mcp.json"
            if _IS_MAC
            else _appdata() / "Highlight" / "mcp.json"
        ),
        "key": "mcpServers",
    },
}

_ENGRAM_MCP_ENTRY = {
    "command": "uvx",
    "args": ["--from", "engram-team@latest", "engram", "serve"],
}

# ── Agent steering / instructions ────────────────────────────────────
# After writing the MCP config, we also write agent instruction files so
# the LLM knows what Engram is and how to use it without the user having
# to explain.  Each IDE has its own convention for persistent agent rules.

_ENGRAM_AGENT_INSTRUCTIONS = """\
# Engram — Shared Team Memory

You have access to an MCP tool called **Engram**. It gives you a shared
memory layer so every agent on the team sees the same verified facts.

## On every new session
1. Call `engram_status()` first. Read the `next_prompt` field and follow it.
2. If status is `ready`, call `engram_query("<topic>")` before starting
   any task to see what the team already knows.

## While working
- After verifying a non-obvious discovery (hidden side-effect, config
  detail, failed approach, architectural decision), call `engram_commit`.
- Before architectural decisions, call `engram_conflicts()` to check for
  disputed facts.

## Rules
- Only commit facts you have verified — never speculative claims.
- Do not include secrets, API keys, or passwords in commits.
- Batch related discoveries into one commit (max 5 commits per task).
- Do not call `engram_query` more than 3 times per task.
"""

# Map of IDE name → list of (file_path, content_or_callable) for steering.
# Paths are relative to the user's home directory or absolute.
# We only write to IDEs that were detected (config file exists).
_STEERING_LOCATIONS: dict[str, list[tuple[Path, str]]] = {
    "Kiro": [
        (Path.home() / ".kiro" / "steering" / "engram.md", _ENGRAM_AGENT_INSTRUCTIONS),
    ],
    "Claude Code": [
        (Path.home() / ".claude" / "CLAUDE.md", _ENGRAM_AGENT_INSTRUCTIONS),
    ],
    "Cursor": [
        (Path.home() / ".cursor" / "rules" / "engram.mdc", _ENGRAM_AGENT_INSTRUCTIONS),
    ],
    "Windsurf": [
        (Path.home() / ".codeium" / "windsurf" / "rules" / "engram.md", _ENGRAM_AGENT_INSTRUCTIONS),
    ],
    "Codex": [
        (Path.home() / ".codex" / "AGENTS.md", _ENGRAM_AGENT_INSTRUCTIONS),
    ],
    "VS Code (Copilot)": [
        (Path.home() / ".github" / "copilot-instructions.md", _ENGRAM_AGENT_INSTRUCTIONS),
    ],
    "Amazon Q Developer CLI": [
        (Path.home() / ".aws" / "amazonq" / "rules" / "engram.md", _ENGRAM_AGENT_INSTRUCTIONS),
    ],
    "Gemini CLI": [
        (Path.home() / ".gemini" / "GEMINI.md", _ENGRAM_AGENT_INSTRUCTIONS),
    ],
    "GitHub Copilot CLI": [
        (Path.home() / ".copilot" / "instructions.md", _ENGRAM_AGENT_INSTRUCTIONS),
    ],
}


def _write_steering(client_name: str, dry_run: bool) -> list[str]:
    """Write agent instruction files for a detected IDE. Returns list of written paths."""
    written = []
    locations = _STEERING_LOCATIONS.get(client_name, [])
    for file_path, content in locations:
        try:
            if file_path.exists():
                existing = file_path.read_text()
                if "engram" in existing.lower() and "engram_status" in existing:
                    continue  # already has engram instructions
                # Append to existing file
                if not dry_run:
                    with open(file_path, "a") as f:
                        f.write("\n\n" + content)
                written.append(str(file_path))
            else:
                if not dry_run:
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(content)
                written.append(str(file_path))
        except Exception:
            pass
    return written


@main.command()
@click.option("--dry-run", is_flag=True, help="Show what would be changed without writing.")
def install(dry_run: bool) -> None:
    """Auto-detect MCP clients and add Engram to their config."""
    added = []
    skipped = []
    steering_written = []

    for client_name, info in _MCP_CLIENTS.items():
        config_path: Path = info["path"]
        key: str = info["key"]
        fmt = info.get("format", "json")

        try:
            if fmt == "toml":
                # Handle TOML format (Codex)
                try:
                    import tomli
                    import tomli_w

                    if config_path.exists():
                        data = tomli.loads(config_path.read_text())
                    else:
                        data = {}

                    servers = data.setdefault(key, {})
                    
                    if "engram" in servers:
                        skipped.append(client_name)
                        steering_written.extend(_write_steering(client_name, dry_run))
                        continue
                    
                    servers["engram"] = {
                        "command": "uvx",
                        "args": ["--from", "engram-team@latest", "engram", "serve"],
                    }
                    
                    if not dry_run:
                        config_path.parent.mkdir(parents=True, exist_ok=True)
                        config_path.write_text(tomli_w.dumps(data))
                    
                    added.append(client_name)
                    steering_written.extend(_write_steering(client_name, dry_run))
                except ImportError:
                    click.echo(f"Warning: tomli/tomli_w not installed, skipping {client_name}")
                    continue
            else:
                # Handle JSON format
                if config_path.exists():
                    data = json.loads(config_path.read_text())
                else:
                    data = {}

                servers = data.setdefault(key, {})

                if "engram" in servers:
                    skipped.append(client_name)
                    steering_written.extend(_write_steering(client_name, dry_run))
                    continue

                servers["engram"] = _ENGRAM_MCP_ENTRY

                if not dry_run:
                    config_path.parent.mkdir(parents=True, exist_ok=True)
                    config_path.write_text(json.dumps(data, indent=2))

                added.append(client_name)
                steering_written.extend(_write_steering(client_name, dry_run))
        except Exception as e:
            click.echo(f"Warning: Failed to process {client_name}: {e}")
            continue

    # Also try Claude Code CLI if available
    _try_claude_code_cli(dry_run, added, skipped)

    if added:
        click.echo(f"✓ Engram added to: {', '.join(added)}")
    if skipped:
        click.echo(f"⊙ Already configured: {', '.join(skipped)}")
    if steering_written:
        click.echo(f"📝 Agent instructions written to: {', '.join(steering_written)}")

    if added:
        click.echo("\n→ Restart your editor and ask your agent: 'Set up Engram for my team'")
    elif not added and not skipped:
        click.echo(
            "\nNo MCP clients detected. Add Engram manually:\n\n"
            '  {"mcpServers": {"engram": {"command": "uvx", "args": ["--from", "engram-team@latest", "engram", "serve"]}}}'
        )



def _try_claude_code_cli(dry_run: bool, added: list, skipped: list) -> None:
    """Try adding via 'claude mcp add' CLI if claude is available."""
    import shutil
    import subprocess

    if not shutil.which("claude"):
        return
    # Check if already added via settings.json (avoid double-add)
    settings = Path.home() / ".claude" / "settings.json"
    if settings.exists():
        try:
            data = json.loads(settings.read_text())
            if "engram" in data.get("mcpServers", {}):
                return  # already handled above
        except Exception:
            pass

    if dry_run:
        click.echo("[dry-run] Would run: claude mcp add engram --command uvx -- --from engram-team@latest engram serve")
        return

    try:
        result = subprocess.run(
            ["claude", "mcp", "add", "engram", "--command", "uvx", "--", "--from", "engram-team@latest", "engram", "serve"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            added.append("Claude Code (via CLI)")
        elif "already" in result.stdout.lower() or "already" in result.stderr.lower():
            skipped.append("Claude Code (via CLI)")
    except Exception:
        pass


# ── engram serve ─────────────────────────────────────────────────────


@main.command()
@click.option("--http", is_flag=True, help="Streamable HTTP transport.")
@click.option("--host", default="127.0.0.1", help="Host to bind.")
@click.option("--port", default=7474, type=int, help="Port to bind.")
@click.option("--db", default=None, help="SQLite path (local mode only).")
@click.option("--log-level", default="INFO", help="Logging level.")
@click.option("--auth", is_flag=True, help="Enable JWT auth (legacy team mode).")
@click.option("--rate-limit", default=50, type=int, help="Commits/agent/hr.")
def serve(
    http: bool, host: str, port: int, db: str | None, log_level: str,
    auth: bool, rate_limit: int,
) -> None:
    """Start the Engram MCP server."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    lgr = logging.getLogger("engram")
    asyncio.run(_serve(
        http=http, host=host, port=port, db_path=db, logger=lgr,
        auth_enabled=auth, rate_limit=rate_limit,
    ))


async def _serve(
    http: bool, host: str, port: int, db_path: str | None, logger: logging.Logger,
    auth_enabled: bool = False, rate_limit: int = 50,
) -> None:
    import os

    from engram.engine import EngramEngine
    from engram.server import mcp, set_rate_limiter, set_auth_enabled
    import engram.server as server_module

    # ── Select storage backend ────────────────────────────────────────
    db_url = os.environ.get("ENGRAM_DB_URL", "")
    workspace_id = "local"
    schema = "engram"

    # Try to read workspace.json for db_url, workspace_id, and schema
    try:
        from engram.workspace import read_workspace
        ws = read_workspace()
        if ws and ws.db_url:
            db_url = ws.db_url
            workspace_id = ws.engram_id
            schema = ws.schema
    except Exception:
        pass

    if db_url:
        from engram.postgres_storage import PostgresStorage
        storage = PostgresStorage(db_url=db_url, workspace_id=workspace_id, schema=schema)
        logger.info("Team mode: PostgreSQL (workspace: %s, schema: %s)", workspace_id, schema)
    else:
        from engram.storage import SQLiteStorage
        effective_db = db_path or str(DEFAULT_DB_PATH)
        storage = SQLiteStorage(db_path=effective_db)
        logger.info("Local mode: SQLite (%s)", effective_db)

    await storage.connect()

    engine = EngramEngine(storage)
    server_module._engine = engine
    server_module._storage = storage

    if auth_enabled:
        set_auth_enabled(True)
        logger.info("JWT auth enabled")
    if rate_limit:
        from engram.auth import RateLimiter
        set_rate_limiter(RateLimiter(max_per_hour=rate_limit))
        logger.info("Rate limit: %d commits/agent/hour", rate_limit)

    await engine.start()

    expired = await storage.expire_ttl_facts()
    if expired:
        logger.info("Expired %d TTL facts on startup", expired)

    try:
        if http:
            logger.info("Starting Streamable HTTP on %s:%d", host, port)
            logger.info("Dashboard: http://%s:%d/dashboard", host, port)
            from engram.dashboard import build_dashboard_routes
            from engram.federation import build_federation_routes
            from starlette.applications import Starlette
            from starlette.routing import Mount

            dashboard_routes = build_dashboard_routes(storage)
            federation_routes = build_federation_routes(storage)
            app = Starlette(
                routes=dashboard_routes + federation_routes + [
                    Mount("/", app=mcp.streamable_http_app()),
                ],
            )
            import uvicorn
            config = uvicorn.Config(app, host=host, port=port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
        else:
            logger.info("Starting stdio server")
            await mcp.run_stdio_async()
    finally:
        await engine.stop()
        await storage.close()


# ── engram token ─────────────────────────────────────────────────────


@main.group()
def token() -> None:
    """Manage authentication tokens."""
    pass


@token.command("create")
@click.option("--engineer", required=True, help="Engineer email or id.")
@click.option("--agent-id", default=None, help="Optional agent id.")
@click.option("--expires-hours", default=720, type=int, help="Token lifetime (hours).")
def token_create(engineer: str, agent_id: str | None, expires_hours: int) -> None:
    """Create a new bearer token for an engineer."""
    from engram.auth import create_token
    tok = create_token(engineer=engineer, agent_id=agent_id, expires_hours=expires_hours)
    click.echo(tok)


if __name__ == "__main__":
    main()
