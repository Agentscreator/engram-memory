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

from engram import embeddings
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
        "path": Path.home()
        / ".vscode"
        / "globalStorage"
        / "saoudrizwan.claude-dev"
        / "settings"
        / "cline_mcp_settings.json",
        "key": "mcpServers",
    },
    "Cline (VS Code Insiders)": {
        "path": Path.home()
        / ".vscode-insiders"
        / "globalStorage"
        / "saoudrizwan.claude-dev"
        / "settings"
        / "cline_mcp_settings.json",
        "key": "mcpServers",
    },
    "Roo Code (VS Code)": {
        "path": Path.home()
        / ".vscode"
        / "globalStorage"
        / "rooveterinaryinc.roo-cline"
        / "settings"
        / "cline_mcp_settings.json",
        "key": "mcpServers",
    },
    "Roo Code (VS Code Insiders)": {
        "path": Path.home()
        / ".vscode-insiders"
        / "globalStorage"
        / "rooveterinaryinc.roo-cline"
        / "settings"
        / "cline_mcp_settings.json",
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
        click.echo(
            "[dry-run] Would run: claude mcp add engram --command uvx -- --from engram-team@latest engram serve"
        )
        return

    try:
        result = subprocess.run(
            [
                "claude",
                "mcp",
                "add",
                "engram",
                "--command",
                "uvx",
                "--",
                "--from",
                "engram-team@latest",
                "engram",
                "serve",
            ],
            capture_output=True,
            text=True,
            timeout=10,
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
    http: bool,
    host: str,
    port: int,
    db: str | None,
    log_level: str,
    auth: bool,
    rate_limit: int,
) -> None:
    """Start the Engram MCP server."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    lgr = logging.getLogger("engram")
    asyncio.run(
        _serve(
            http=http,
            host=host,
            port=port,
            db_path=db,
            logger=lgr,
            auth_enabled=auth,
            rate_limit=rate_limit,
        )
    )


async def _serve(
    http: bool,
    host: str,
    port: int,
    db_path: str | None,
    logger: logging.Logger,
    auth_enabled: bool = False,
    rate_limit: int = 50,
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

    # Check for mixed embedding models and warn
    try:
        models = await storage.get_distinct_embedding_models()
        if len(models) > 1:
            current = embeddings.get_model_name()
            other_models = [m for m in models if m != current]
            logger.warning(
                "⚠ Mixed embedding models detected: %s. "
                "Facts with models %s may produce incorrect similarity results. "
                "Run 'engram re-embed' to update embeddings.",
                models,
                other_models,
            )
            click.echo(
                f"\n⚠ WARNING: Mixed embedding models detected: {models}\n"
                f"  Current model: {current}\n"
                f"  Other models: {other_models}\n"
                f"  Run 'engram re-embed' to fix embeddings.\n"
            )
    except Exception:
        pass

    try:
        if http:
            logger.info("Starting Streamable HTTP on %s:%d", host, port)
            logger.info("Dashboard: http://%s:%d/dashboard", host, port)
            from engram.dashboard import build_dashboard_routes
            from engram.federation import build_federation_routes
            import uvicorn
            from starlette.routing import Mount, Route

            dashboard_routes = build_dashboard_routes(storage)
            federation_routes = build_federation_routes(storage)
            mcp_app = mcp.streamable_http_app()

            # Add routes to MCP app
            mcp_app.router.routes.extend(
                [
                    Mount("/dashboard", routes=dashboard_routes),
                    Mount("/api/federation", routes=federation_routes),
                ]
            )

            config = uvicorn.Config(mcp_app, host=host, port=port, log_level="info")
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


# ── engram verify ────────────────────────────────────────────────────


@main.command()
@click.option("--verbose", "-v", is_flag=True, help="Show details for all checks.")
def verify(verbose: bool) -> None:
    """Verify Engram installation and configuration.

    Runs a focused checklist and prints a clear pass/fail for each:
    ✓ workspace.json exists and is valid
    ✓ Backend is reachable (team mode)
    ✓ MCP config written to at least one IDE
    ✓ NLI model files present (if using conflict detection)
    """
    from engram.workspace import WORKSPACE_PATH, read_workspace
    import json
    import urllib.request
    import urllib.error
    import os

    all_passed = True
    verbose = verbose or os.environ.get("ENGRAM_VERIFY_VERBOSE") == "1"

    # Check 1: workspace.json exists and is valid JSON
    click.echo("\n[1/4] Checking workspace configuration...")
    if not WORKSPACE_PATH.exists():
        click.echo(f"  ✗ ~/.engram/workspace.json not found")
        click.echo(f"    → Run: engram init   (or: engram join <key>)")
        click.echo(
            f"    → Docs: https://github.com/Agentscreator/Engram/blob/main/docs/QUICKSTART.md"
        )
        all_passed = False
    else:
        try:
            data = json.loads(WORKSPACE_PATH.read_text())
            ws = read_workspace()
            mode = "team" if ws and ws.db_url else "local"
            click.echo(f"  ✓ workspace.json exists ({mode} mode)")
            if verbose:
                click.echo(f"    - engram_id: {ws.engram_id if ws else 'N/A'}")
                click.echo(f"    - schema: {ws.schema if ws else 'N/A'}")
                click.echo(f"    - anonymous_mode: {ws.anonymous_mode if ws else 'N/A'}")
        except json.JSONDecodeError as e:
            click.echo(f"  ✗ workspace.json is invalid JSON: {e}")
            click.echo(f"    → Delete and re-run: rm ~/.engram/workspace.json && engram init")
            all_passed = False

    # Check 2: Backend is reachable (team mode only)
    click.echo("\n[2/4] Checking backend connectivity...")
    ws = read_workspace()
    if ws and ws.db_url:
        # For team mode, check if we can reach the MCP endpoint
        # The MCP URL pattern is derived from db_url or uses default
        mcp_url = os.environ.get("ENGRAM_MCP_URL", "https://mcp.engram.app/mcp")

        # Try a simple HEAD request to check connectivity
        try:
            req = urllib.request.Request(
                mcp_url.replace("/mcp", "/health") if "/mcp" in mcp_url else mcp_url, method="HEAD"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status < 400:
                    click.echo(f"  ✓ Backend reachable at {mcp_url}")
                else:
                    click.echo(f"  ✗ Backend returned status {resp.status}")
                    all_passed = False
        except urllib.error.URLError as e:
            # Non-critical: backend might not have /health endpoint
            click.echo(f"  ⚠ Could not reach health endpoint (non-critical)")
            if verbose:
                click.echo(f"    - URL: {mcp_url}")
                click.echo(f"    - Error: {e.reason}")
                click.echo(f"    - Note: Backend connectivity will be verified by your IDE")
        except Exception as e:
            click.echo(f"  ⚠ Could not verify backend ({type(e).__name__}: {e})")
            if verbose:
                click.echo(f"    - This is normal if you're offline or the backend is busy")
    else:
        click.echo("  ○ Team mode not configured (local SQLite mode)")
        if verbose:
            click.echo("    - For team features: engram init or engram join <key>")

    # Check 3: MCP config in at least one IDE
    click.echo("\n[3/4] Checking MCP configuration in IDEs...")
    detected = []
    missing = []

    for client_name, info in _MCP_CLIENTS.items():
        config_path: Path = info["path"]
        try:
            if config_path.exists():
                data = json.loads(config_path.read_text())
                key = info["key"]

                # Navigate nested keys (e.g., "mcpServers" or "mcp")
                keys = key.split(".")
                current = data
                found = True
                for k in keys:
                    if isinstance(current, dict) and k in current:
                        current = current[k]
                    else:
                        found = False
                        break

                if found and isinstance(current, dict) and "engram" in current:
                    detected.append(client_name)
                else:
                    missing.append(client_name)
        except (json.JSONDecodeError, KeyError, TypeError):
            missing.append(client_name)

    if detected:
        click.echo(f"  ✓ Engram configured in: {', '.join(detected)}")
        if verbose:
            for client_name in detected:
                click.echo(f"    - ✓ {client_name}")
    else:
        click.echo("  ✗ Engram not found in any IDE MCP config")
        click.echo(f"    → Run: engram install")
        all_passed = False

    if missing and verbose:
        click.echo(f"\n  Other detected IDEs (Engram not configured):")
        for client_name in missing[:5]:  # Limit verbose output
            click.echo(f"    - ○ {client_name}")
        if len(missing) > 5:
            click.echo(f"    - ... and {len(missing) - 5} more")

    # Check 4: NLI model files present
    click.echo("\n[4/4] Checking NLI model files...")
    model_dir = Path.home() / ".cache" / "huggingface" / "hub"
    nli_model_path = model_dir / "models--cross-encoder--nli-MiniLM2-L6-H768"

    # Check in common locations
    possible_paths = [
        nli_model_path,
        Path.home() / ".cache" / "sentence_transformers" / "cross-encoder" / "nli-MiniLM2-L6-H768",
    ]

    found_model = False
    for path in possible_paths:
        if path.exists():
            click.echo(f"  ✓ NLI model found at {path}")
            found_model = True
            break

    if not found_model:
        click.echo(f"  ⚠ NLI model not cached (will download on first conflict detection)")
        if verbose:
            click.echo(f"    - Model: cross-encoder/nli-MiniLM2-L6-H768")
            click.echo(f"    - Will be downloaded automatically when needed")
            click.echo(
                f"    - This is optional - Engram works without it (Tier 1 detection disabled)"
            )

    # Summary
    click.echo("\n" + "=" * 50)
    if all_passed:
        click.echo("✓ All checks passed! Engram is ready to use.")
        click.echo("\nNext steps:")
        click.echo("  1. Restart your IDE")
        click.echo("  2. Ask your agent: 'Set up Engram for my team'")
        click.echo("  3. Run 'engram verify' anytime to re-check")
    else:
        click.echo("✗ Some checks failed. Fix the issues above and run 'engram verify' again.")
        click.echo(
            "\nFor help: https://github.com/Agentscreator/Engram/blob/main/docs/TROUBLESHOOTING.md"
        )
    click.echo("=" * 50 + "\n")


# ── engram re-embed ───────────────────────────────────────────────────


@main.command()
@click.option(
    "--model", default=None, help="Re-embed facts with this model. Default: all except current."
)
@click.option("--batch-size", default=50, help="Facts per batch (default: 50).")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be re-embedded without making changes."
)
def reembed(model: str | None, batch_size: int, dry_run: bool) -> None:
    """Re-embed facts when the embedding model changes.

    When switching embedding models (e.g., all-MiniLM-L6-v2 to a 768-dim model),
    existing embeddings become incompatible. This command re-embeds facts
    using the current model.

    Examples:
        engram re-embed              # Re-embed all outdated facts
        engram re-embed --dry-run    # Show what would be re-embedded
        engram re-embed --batch-size 100
    """
    import os
    from engram import embeddings

    # Get current model info
    current_model = embeddings.get_model_name()
    current_ver = embeddings.get_model_version()

    click.echo(f"Current embedding model: {current_model} (v{current_ver})")

    # Determine target model to re-embed
    if model:
        target_model = model
        click.echo(f"Target model to re-embed: {target_model}")
    else:
        click.echo("No --model specified, will re-embed all facts not using current model")

    # Set up storage based on environment
    db_url = os.environ.get("ENGRAM_DB_URL", "")
    workspace_id = "local"
    schema = "engram"

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
        mode = "team"
    else:
        from engram.storage import SQLiteStorage, DEFAULT_DB_PATH

        storage = SQLiteStorage(db_path=str(DEFAULT_DB_PATH))
        mode = "local"

    async def run_reembed():
        await storage.connect()
        try:
            # Get distinct models in workspace
            models = await storage.get_distinct_embedding_models()
            click.echo(f"\nEmbedding models in workspace: {models}")

            # Determine which models need re-embedding
            if model:
                models_to_reembed = [model] if model in models else []
            else:
                models_to_reembed = [m for m in models if m != current_model]

            if not models_to_reembed:
                click.echo("\n✓ No facts need re-embedding (all using current model)")
                return

            click.echo(f"Models to re-embed: {models_to_reembed}")

            total_reembedded = 0
            for target in models_to_reembed:
                click.echo(f"\nRe-embedding facts from '{target}'...")

                # Get count
                facts = await storage.get_facts_by_embedding_model(target, limit=1, offset=0)
                if not facts:
                    continue

                # Count total
                import asyncio

                all_facts = await storage.get_facts_by_embedding_model(
                    target, limit=100000, offset=0
                )
                total = len(all_facts)
                click.echo(f"  Found {total} facts to re-embed")

                if dry_run:
                    click.echo(f"  [DRY RUN] Would re-embed {total} facts")
                    continue

                # Re-embed in batches
                offset = 0
                while offset < total:
                    batch = await storage.get_facts_by_embedding_model(
                        target, limit=batch_size, offset=offset
                    )
                    if not batch:
                        break

                    for fact in batch:
                        # Re-embed the content
                        new_emb = embeddings.encode(fact["content"])
                        emb_bytes = embeddings.embedding_to_bytes(new_emb)
                        await storage.update_fact_embedding_with_model(
                            fact["id"], emb_bytes, current_model, current_ver
                        )
                        total_reembedded += 1

                    click.echo(f"  Processed {min(offset + batch_size, total)}/{total}")
                    offset += batch_size

                click.echo(f"  ✓ Re-embedded {total} facts from '{target}'")

            click.echo(f"\n✓ Total re-embedded: {total_reembedded}")

        finally:
            await storage.close()

    asyncio.run(run_reembed())


if __name__ == "__main__":
    main()
