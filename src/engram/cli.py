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


# Known MCP client config locations and the JSON path to mcpServers
_MCP_CLIENTS = {
    "Claude Code": {
        "path": Path.home() / ".claude" / "settings.json",
        "key": "mcpServers",
    },
    "Claude Desktop": {
        "path": Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        "key": "mcpServers",
    },
    "Cursor": {
        "path": Path.home() / ".cursor" / "mcp.json",
        "key": "mcpServers",
    },
    "Windsurf": {
        "path": Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
        "key": "mcpServers",
    },
    "Cline (VS Code)": {
        "path": Path.home() / ".vscode" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json",
        "key": "mcpServers",
    },
    "Roo Code (VS Code)": {
        "path": Path.home() / ".vscode" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json",
        "key": "mcpServers",
    },
    "VS Code (Copilot)": {
        "path": Path.home() / ".vscode" / "mcp.json",
        "key": "mcpServers",
    },
    "Codex": {
        "path": Path.home() / ".codex" / "config.toml",
        "key": "mcp_servers",  # TOML format
        "format": "toml",
    },
}

_ENGRAM_MCP_ENTRY = {
    "command": "uvx",
    "args": ["engram-team@latest"],
}


@main.command()
@click.option("--dry-run", is_flag=True, help="Show what would be changed without writing.")
def install(dry_run: bool) -> None:
    """Auto-detect MCP clients and add Engram to their config."""
    added = []
    skipped = []
    not_found = []

    for client_name, info in _MCP_CLIENTS.items():
        config_path: Path = info["path"]
        key: str = info["key"]
        fmt = info.get("format", "json")

        if not config_path.exists():
            not_found.append(client_name)
            continue

        try:
            if fmt == "toml":
                # Handle TOML format (Codex)
                try:
                    import tomli
                    import tomli_w
                    data = tomli.loads(config_path.read_text())
                    servers = data.setdefault(key, {})
                    
                    if "engram" in servers:
                        skipped.append(client_name)
                        continue
                    
                    servers["engram"] = {
                        "command": "uvx",
                        "args": ["engram-team@latest"],
                    }
                    
                    if not dry_run:
                        config_path.parent.mkdir(parents=True, exist_ok=True)
                        config_path.write_text(tomli_w.dumps(data))
                    
                    added.append(client_name)
                except ImportError:
                    click.echo(f"Warning: tomli/tomli_w not installed, skipping {client_name}")
                    continue
            else:
                # Handle JSON format
                data = json.loads(config_path.read_text())
                servers = data.setdefault(key, {})

                if "engram" in servers:
                    skipped.append(client_name)
                    continue

                servers["engram"] = _ENGRAM_MCP_ENTRY

                if not dry_run:
                    config_path.parent.mkdir(parents=True, exist_ok=True)
                    config_path.write_text(json.dumps(data, indent=2))

                added.append(client_name)
        except Exception as e:
            click.echo(f"Warning: Failed to process {client_name}: {e}")
            continue

    # Also try Claude Code CLI if available
    _try_claude_code_cli(dry_run, added, skipped)

    if added:
        click.echo(f"✓ Engram added to: {', '.join(added)}")
    if skipped:
        click.echo(f"⊙ Already configured: {', '.join(skipped)}")
    if not_found:
        click.echo(f"⊘ Not installed (skipped): {', '.join(not_found)}")

    if added:
        click.echo("\n→ Restart your editor and ask your agent: 'Set up Engram for my team'")
    elif not added and not skipped:
        click.echo(
            "\nNo MCP clients detected. Add Engram manually:\n\n"
            '  {"mcpServers": {"engram": {"command": "uvx", "args": ["engram-team@latest"]}}}'
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
        click.echo("[dry-run] Would run: claude mcp add engram --command uvx -- engram-team@latest")
        return

    try:
        result = subprocess.run(
            ["claude", "mcp", "add", "engram", "--command", "uvx", "--", "engram-team@latest"],
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
