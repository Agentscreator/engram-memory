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
import os

import click

from engram import embeddings
from engram.storage import DEFAULT_DB_PATH

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_PATH_SYSTEM_HOME = Path.home()
_PATH_APPDATA_DIR = Path(os.environ["APPDATA"]) if "APPDATA" in os.environ else None
_PATH_APPSUPPORT_DIR = _PATH_SYSTEM_HOME / "Library" / "Application Support"  # Mac only
_PATH_XDG_DIR = (
    Path(os.environ["XDG_CONFIG_HOME"])
    if "XDG_CONFIG_HOME" in os.environ
    else _PATH_SYSTEM_HOME / ".config"
)


@click.group()
def main() -> None:
    """Engram - Multi-agent memory consistency for engineering teams."""
    pass


# ── engram install ───────────────────────────────────────────────────

# Read in the list of known client config locations and get their appropriate
# config file (different systems have them in different places).

_MCP_CLIENTS = {}
with open(os.path.join(_DATA_DIR, "cli-agent-clients.json"), "r") as file:
    agent_clients_json = json.load(file)
    for key in agent_clients_json.keys():
        _MCP_CLIENTS[key] = {}
        agent_config_path = agent_clients_json[key]["path"]
        if agent_clients_json[key]["config_path"]["appdata"] and _PATH_APPDATA_DIR:
            _MCP_CLIENTS[key]["path"] = Path(_PATH_APPDATA_DIR / agent_config_path)
        elif agent_clients_json[key]["config_path"]["appsupport"] and _PATH_APPSUPPORT_DIR:
            _MCP_CLIENTS[key]["path"] = Path(_PATH_APPSUPPORT_DIR / agent_config_path)
        elif agent_clients_json[key]["config_path"]["xdg"] and _PATH_XDG_DIR:
            _MCP_CLIENTS[key]["path"] = Path(_PATH_XDG_DIR / agent_config_path)
        elif agent_clients_json[key]["config_path"]["syshome"]:
            _MCP_CLIENTS[key]["path"] = Path(_PATH_SYSTEM_HOME / agent_config_path)
        if "path" not in _MCP_CLIENTS[key]:
            _MCP_CLIENTS[key]["path"] = Path("ValidPathNotFound")
        _MCP_CLIENTS[key]["key"] = agent_clients_json[key]["server_type_key"]

_ENGRAM_MCP_ENTRY = {
    "command": "uvx",
    "args": ["--from", "engram-team@latest", "engram", "serve"],
}


def _engram_mcp_entry_for_client(client_name: str) -> dict[str, object]:
    import os

    mcp_url = os.environ.get("ENGRAM_MCP_URL", "https://mcp.engram.app/mcp")

    if client_name == "Windsurf":
        return {"serverUrl": mcp_url}

    if client_name == "Zed":
        return {"url": mcp_url}

    return {
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

                servers["engram"] = _engram_mcp_entry_for_client(client_name)

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
        storage = SQLiteStorage(db_path=effective_db, workspace_id=workspace_id)
        logger.info("Local mode: SQLite (%s, workspace: %s)", effective_db, workspace_id)

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
            from engram.rest import build_rest_routes
            import uvicorn
            from starlette.routing import Mount

            dashboard_routes = build_dashboard_routes(storage)
            federation_routes = build_federation_routes(storage)
            rest_routes = build_rest_routes(
                engine=engine,
                storage=storage,
                auth_enabled=auth_enabled,
                rate_limiter=server_module._rate_limiter,
            )
            mcp_app = mcp.streamable_http_app()

            # Add routes to MCP app
            mcp_app.router.routes.extend(
                [
                    Mount("/dashboard", routes=dashboard_routes),
                    Mount("/api/federation", routes=federation_routes),
                    *rest_routes,
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


# ── engram config ────────────────────────────────────────────────────


@main.group()
def config() -> None:
    """Show and update workspace settings."""
    pass


@config.command("show")
def config_show() -> None:
    """Pretty-print the current editable workspace settings."""
    from engram.workspace import read_workspace_settings

    try:
        settings = read_workspace_settings()
    except ValueError as e:
        raise click.ClickException(str(e))

    click.echo(json.dumps(settings, indent=2))


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Update a single editable workspace setting."""
    from engram.workspace import parse_config_value, set_workspace_setting

    try:
        parsed_value = parse_config_value(key, value)
        set_workspace_setting(key, value)
    except ValueError as e:
        raise click.ClickException(str(e))

    click.echo(f"Updated {key}={json.dumps(parsed_value)}")


# ── engram search ────────────────────────────────────────────────────


def _format_search_results(topic: str, results: list[dict[str, object]]) -> str:
    """Format search results for human-readable terminal output."""
    if not results:
        return f'No results found for "{topic}".'

    lines = [f'Results for "{topic}" ({len(results)}):']
    for idx, fact in enumerate(results, start=1):
        scope = fact.get("scope") or "-"
        content = fact.get("content") or ""
        lines.append(f"{idx}. [{scope}] {content}")

        meta: list[str] = []
        if fact.get("fact_type"):
            meta.append(f"type={fact['fact_type']}")
        if fact.get("confidence") is not None:
            meta.append(f"confidence={fact['confidence']:.2f}")
        if fact.get("verified"):
            meta.append("verified=yes")
        if fact.get("provenance"):
            meta.append(f"provenance={fact['provenance']}")
        if fact.get("has_open_conflict"):
            meta.append("open_conflict=yes")

        if meta:
            lines.append("   " + " ".join(meta))

    return "\n".join(lines)


async def _search_once(topic: str, scope: str | None, limit: int, as_json: bool) -> str:
    """Run one terminal search against the current workspace."""
    import os

    from engram.engine import EngramEngine

    logger = logging.getLogger("engram")

    # Match the same backend-selection logic used by serve()
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
        logger.info("Search mode: PostgreSQL (workspace: %s, schema: %s)", workspace_id, schema)
    else:
        from engram.storage import SQLiteStorage

        storage = SQLiteStorage(db_path=str(DEFAULT_DB_PATH), workspace_id=workspace_id)
        logger.info("Search mode: SQLite (%s, workspace: %s)", DEFAULT_DB_PATH, workspace_id)

    await storage.connect()
    engine = EngramEngine(storage)

    try:
        results = await engine.query(topic=topic, scope=scope, limit=limit)
    finally:
        await storage.close()

    if as_json:
        return json.dumps(results, indent=2)

    return _format_search_results(topic, results)


@main.command()
@click.argument("topic")
@click.option("--scope", default=None, help="Optional scope prefix to filter results.")
@click.option(
    "--limit",
    default=10,
    type=click.IntRange(1, 50),
    show_default=True,
    help="Maximum results to print.",
)
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON results for piping.")
def search(topic: str, scope: str | None, limit: int, as_json: bool) -> None:
    """Query the workspace directly from the terminal without an agent session."""
    try:
        output = asyncio.run(
            _search_once(
                topic=topic,
                scope=scope,
                limit=limit,
                as_json=as_json,
            )
        )
    except Exception as exc:
        raise click.ClickException(str(exc))

    click.echo(output)


# ── engram tail ──────────────────────────────────────────────────────


def _format_tail_fact(fact: dict[str, object]) -> str:
    """Format one fact for streaming terminal output."""
    agent = fact.get("agent_id") or "unknown"
    scope = fact.get("scope") or "-"
    content = fact.get("content") or ""
    confidence = fact.get("confidence")

    if confidence is not None:
        return f"[{agent}] [{scope}] {content} (confidence: {confidence:.2f})"

    return f"[{agent}] [{scope}] {content}"


async def _tail_once(
    base_url: str,
    after: str,
    scope: str | None,
    limit: int,
) -> tuple[list[dict[str, object]], str]:
    """Fetch facts newer than the watermark from the REST API."""
    import urllib.parse
    import urllib.request

    params = {"after": after, "limit": str(limit)}
    if scope:
        params["scope"] = scope

    url = f"{base_url.rstrip('/')}/api/tail?{urllib.parse.urlencode(params)}"

    with urllib.request.urlopen(url, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    facts = payload.get("facts", [])
    latest_timestamp = payload.get("latest_timestamp", after)
    return facts, latest_timestamp


@main.command()
@click.option("--scope", default=None, help="Optional scope prefix to filter streamed facts.")
@click.option(
    "--limit",
    default=100,
    type=click.IntRange(1, 1000),
    show_default=True,
    help="Maximum facts per poll.",
)
@click.option(
    "--interval",
    default=2.0,
    type=float,
    show_default=True,
    help="Polling interval in seconds.",
)
@click.option(
    "--url",
    "base_url",
    default="http://127.0.0.1:7474",
    show_default=True,
    help="Base URL for the Engram HTTP server.",
)
def tail(scope: str | None, limit: int, interval: float, base_url: str) -> None:
    """Stream new workspace facts from the terminal."""
    from datetime import datetime, timezone

    click.echo("Starting tail stream. Press Ctrl+C to stop.")

    after = datetime.now(timezone.utc).isoformat()

    try:
        while True:
            facts, latest_timestamp = asyncio.run(
                _tail_once(
                    base_url=base_url,
                    after=after,
                    scope=scope,
                    limit=limit,
                )
            )

            for fact in facts:
                click.echo(_format_tail_fact(fact))

            after = latest_timestamp
            import time

            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    except Exception as exc:
        raise click.ClickException(str(exc))


# ── engram status ───────────────────────────────────────────────────────


@main.command()
def status() -> None:
    """Show current workspace status and connection info.

    Displays:
    - Workspace ID and mode (local/team)
    - Connection status
    - Anonymous mode settings
    - Schema info
    """
    import os
    from engram.workspace import read_workspace, WORKSPACE_PATH

    ws = read_workspace()

    if not ws and not WORKSPACE_PATH.exists():
        db_url = os.environ.get("ENGRAM_DB_URL", "")
        if not db_url:
            click.echo("=== Engram Status ===")
            click.echo("Status: Not configured")
            click.echo("\nTo get started:")
            click.echo("  1. Set ENGRAM_DB_URL (or use engram join <invite-key>)")
            click.echo("  2. Run: engram setup")
            return

    ws = read_workspace()
    if not ws:
        click.echo("Error: Invalid workspace configuration")
        return

    mode = "Team (PostgreSQL)" if ws.db_url else "Local (SQLite)"
    click.echo("=== Engram Status ===")
    click.echo(f"Workspace ID: {ws.engram_id}")
    click.echo(f"Mode: {mode}")
    click.echo(f"Anonymous Mode: {'Enabled' if ws.anonymous_mode else 'Disabled'}")
    click.echo(f"Anon Agents: {'Enabled' if ws.anon_agents else 'Disabled'}")

    if ws.display_name:
        click.echo(f"Display Name: {ws.display_name}")

    click.echo(f"\nSchema: {ws.schema}")


# ── engram stats ───────────────────────────────────────────────────────────


@main.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON.")
def stats(output_json: bool) -> None:
    """Show workspace statistics: fact count, conflicts, agents."""
    import os
    import urllib.request
    import urllib.error

    ws = None
    try:
        from engram.workspace import read_workspace

        ws = read_workspace()
    except Exception:
        pass

    if not ws:
        click.echo("Error: No workspace configured")
        return

    mcp_url = os.environ.get("ENGRAM_MCP_URL", "http://localhost:7474")
    base_url = mcp_url.replace("/mcp", "") if "/mcp" in mcp_url else mcp_url

    try:
        url = f"{base_url}/api/stats"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

            if output_json:
                click.echo(json.dumps({"workspace_id": ws.engram_id, **data}, indent=2))
            else:
                facts = data.get("facts", {})
                conflicts = data.get("conflicts", {})
                agents = data.get("agents", {})
                click.echo("=== Workspace Stats ===")
                click.echo(f"Workspace: {ws.engram_id}")
                click.echo(f"Mode: {'Team' if ws.db_url else 'Local'}")
                click.echo(f"Total Facts: {facts.get('total', 0)}")
                click.echo(f"Current Facts: {facts.get('current', 0)}")
                click.echo(f"Expiring Soon: {facts.get('expiring_soon', 0)}")
                click.echo(f"Open Conflicts: {conflicts.get('open', 0)}")
                click.echo(f"Resolved: {conflicts.get('resolved', 0)}")
                click.echo(f"Total Agents: {agents.get('total', 0)}")
    except urllib.error.HTTPError:
        click.echo("=== Workspace Stats ===")
        click.echo(f"Workspace: {ws.engram_id}")
        click.echo(f"Mode: {'Team' if ws.db_url else 'Local'}")
        click.echo("(Run engram serve --http to see full stats)")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


# ── engram whoami ───────────────────────────────────────────────────────────


@main.command()
def whoami() -> None:
    """Show current user identity and agent info.

    Displays:
    - Current engineer ID (if set)
    - Agent ID (if set)
    - Anonymous mode status
    """
    from engram.workspace import read_workspace
    import os

    ws = read_workspace()

    if not ws:
        click.echo("=== Engram Identity ===")
        click.echo("Status: Not configured")
        return

    engineer = os.environ.get("ENGRAM_ENGINEER", os.environ.get("USER", "unknown"))
    agent_id = os.environ.get("ENGRAM_AGENT_ID", "auto-generated")

    click.echo("=== Engram Identity ===")
    click.echo(f"Engineer: {engineer}")
    click.echo(f"Agent ID: {agent_id}")
    click.echo(f"Anonymous Mode: {'Enabled' if ws.anonymous_mode else 'Disabled'}")

    if ws.anon_agents:
        click.echo("Note: Agent ID is randomized each session")


# ── engram info ───────────────────────────────────────────────────────────────


@main.command()
def info() -> None:
    """Display detailed workspace information and connection status.

    Combines output from status, whoami, and config show in one command.
    """
    from engram.workspace import read_workspace, WORKSPACE_PATH
    import os

    ws = read_workspace()

    if not ws and not WORKSPACE_PATH.exists():
        db_url = os.environ.get("ENGRAM_DB_URL", "")
        if not db_url:
            click.echo("=== Engram Info ===")
            click.echo("Status: Not configured")
            click.echo("\nTo get started:")
            click.echo("  1. Set ENGRAM_DB_URL or use engram join <invite-key>")
            click.echo("  2. Run: engram setup")
            return

    ws = read_workspace()
    if not ws:
        click.echo("Error: Invalid workspace configuration")
        return

    engineer = os.environ.get("ENGRAM_ENGINEER", os.environ.get("USER", "unknown"))
    agent_id = os.environ.get("ENGRAM_AGENT_ID", "auto-generated")

    click.echo("=== Engram Workspace Info ===")
    click.echo(f"Workspace ID: {ws.engram_id}")
    click.echo(f"Mode: {'Team (PostgreSQL)' if ws.db_url else 'Local (SQLite)'}")
    click.echo(f"Schema: {ws.schema}")
    if ws.display_name:
        click.echo(f"Display Name: {ws.display_name}")
    click.echo("")
    click.echo("=== Identity ===")
    click.echo(f"Engineer: {engineer}")
    click.echo(f"Agent ID: {agent_id}")
    click.echo("")
    click.echo("=== Privacy ===")
    click.echo(f"Anonymous Mode: {'Enabled' if ws.anonymous_mode else 'Disabled'}")
    click.echo(f"Anon Agents: {'Enabled' if ws.anon_agents else 'Disabled'}")
    click.echo("")
    click.echo("=== Connection ===")
    if ws.db_url:
        click.echo(
            f"Database: {ws.db_url[:40]}..." if len(ws.db_url) > 40 else f"Database: {ws.db_url}"
        )
    else:
        click.echo("Storage: Local SQLite")
        click.echo(f"Location: {DEFAULT_DB_PATH}")


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
        click.echo("  ✗ ~/.engram/workspace.json not found")
        click.echo("    → Run: engram init   (or: engram join <key>)")
        click.echo(
            "    → Docs: https://github.com/Agentscreator/Engram/blob/main/docs/QUICKSTART.md"
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
            click.echo("    → Delete and re-run: rm ~/.engram/workspace.json && engram init")
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
            click.echo("  ⚠ Could not reach health endpoint (non-critical)")
            if verbose:
                click.echo(f"    - URL: {mcp_url}")
                click.echo(f"    - Error: {e.reason}")
                click.echo("    - Note: Backend connectivity will be verified by your IDE")
        except Exception as e:
            click.echo(f"  ⚠ Could not verify backend ({type(e).__name__}: {e})")
            if verbose:
                click.echo("    - This is normal if you're offline or the backend is busy")
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
        click.echo("    → Run: engram install")
        all_passed = False

    if missing and verbose:
        click.echo("\n  Other detected IDEs (Engram not configured):")
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
        click.echo("  ⚠ NLI model not cached (will download on first conflict detection)")
        if verbose:
            click.echo("    - Model: cross-encoder/nli-MiniLM2-L6-H768")
            click.echo("    - Will be downloaded automatically when needed")
            click.echo(
                "    - This is optional - Engram works without it (Tier 1 detection disabled)"
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
    else:
        from engram.storage import SQLiteStorage, DEFAULT_DB_PATH

        storage = SQLiteStorage(db_path=str(DEFAULT_DB_PATH))

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


# ── engram setup ───────────────────────────────────────────────────────


@main.command()
@click.option("--display-name", default=None, help="Display name for the workspace.")
@click.option(
    "--db-url", default=None, help="PostgreSQL connection URL (or set ENGRAM_DB_URL env var)."
)
@click.option("--schema", default="engram", help="PostgreSQL schema name (default: engram).")
@click.option("--skip-mcp", is_flag=True, help="Skip MCP client configuration.")
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes.")
def setup(
    display_name: str | None, db_url: str | None, schema: str, skip_mcp: bool, dry_run: bool
) -> None:
    """One-command setup: detect MCP clients, initialize workspace, print invite key and CLAUDE.md snippet.

    This is the 5-minute install experience. Run this command and you'll have:
    - MCP clients configured (unless --skip-mcp)
    - Workspace initialized with a generated display name
    - Invite key printed (share with teammates)
    - CLAUDE.md snippet ready to copy-paste

    Examples:
        engram setup                                    # Interactive (prompts for DB URL if needed)
        engram setup --db-url postgres://...           # Non-interactive with DB URL
        engram setup --skip-mcp                        # Skip IDE configuration
    """
    import os

    click.echo("\n=== Engram Setup ===")
    click.echo("Starting one-command setup...\n")

    # Step 1: Choose backend (interactive when no --db-url given)
    if not db_url:
        db_url = os.environ.get("ENGRAM_DB_URL", "")

    backend_mode: str | None = None  # "cloud", "postgres", "sqlite"

    if not db_url and not dry_run:
        try:
            import questionary
        except ImportError:
            click.echo("❌ questionary is required for interactive setup.")
            click.echo("  Run: pip install questionary")
            click.echo("  Or pass --db-url directly.")
            return

        choice = questionary.select(
            "Which storage backend do you want to use?",
            choices=[
                questionary.Choice(
                    "Engram Cloud (Recommended)\n     Hosted backend with dashboard included."
                    " Requires an invite key. Zero infrastructure setup.",
                    value="cloud",
                ),
                questionary.Choice(
                    "PostgreSQL (Self-hosted)\n     Run your own server with pgvector."
                    " Full control, multi-machine support.",
                    value="postgres",
                ),
                questionary.Choice(
                    "SQLite (Local only)\n     No dashboard, no cross-agent sync."
                    " Single machine, offline use only.",
                    value="sqlite",
                ),
                questionary.Choice(
                    "Help me choose",
                    value="help",
                ),
            ],
            use_arrow_keys=True,
        ).ask()

        if choice is None:
            # User hit Ctrl-C
            return

        if choice == "help":
            click.echo("")
            click.echo("Engram storage options:")
            click.echo("")
            click.echo("  Engram Cloud  (Recommended)")
            click.echo("    • Hosted backend managed by the Engram team")
            click.echo("    • Dashboard and invite-key sharing included")
            click.echo("    • Join with:  engram join <invite-key>")
            click.echo("    • No servers to run or maintain")
            click.echo("")
            click.echo("  PostgreSQL (Self-hosted)")
            click.echo("    • You control the database (Neon, Supabase, Railway, or your own)")
            click.echo("    • Required for on-prem / air-gapped environments")
            click.echo("    • Pass your URL:  engram setup --db-url postgres://...")
            click.echo("")
            click.echo("  SQLite (Local only)")
            click.echo("    • Zero config — works offline immediately")
            click.echo("    • Knowledge stays on this machine (no cross-agent sync)")
            click.echo("    • Run:  engram setup --local")
            click.echo("")
            return

        backend_mode = choice

        if backend_mode == "cloud":
            click.echo("")
            click.echo("Engram Cloud selected.")
            click.echo("  To join an existing workspace:  engram join <invite-key>")
            click.echo("  (Cloud workspaces are provisioned via invite key — no DB URL needed.)")
            return

        if backend_mode == "postgres":
            db_url = questionary.text(
                "PostgreSQL connection URL:",
                placeholder="postgres://user:password@host:5432/dbname",
            ).ask()
            if not db_url:
                click.echo("❌ No database URL provided. Aborting.")
                return

        if backend_mode == "sqlite":
            click.echo("")
            click.echo("SQLite mode selected — no database URL needed.")
            db_url = ""  # empty string = SQLite mode throughout

    # Step 2: Detect and configure MCP clients
    if skip_mcp:
        click.echo("[1/4] Skipping MCP configuration (--skip-mcp)")
    else:
        click.echo("[1/4] Detecting MCP clients...")
        # Reuse the install logic to detect clients
        added = []
        for client_name, info in _MCP_CLIENTS.items():
            config_path: Path = info["path"]
            if config_path.exists():
                added.append(client_name)

        if added:
            click.echo(f"  Found {len(added)} MCP clients: {', '.join(added[:5])}")
            if not dry_run:
                # Actually run install (this writes the config)
                from click.testing import CliRunner
                from engram.cli import install

                runner = CliRunner()
                result = runner.invoke(install, ["--dry-run" if dry_run else ""])
                click.echo(f"  Would configure: {', '.join(added)}")
        else:
            click.echo("  No MCP clients detected")

    # Step 3: Initialize workspace
    click.echo("[2/4] Initializing workspace...")

    if dry_run:
        click.echo("  [DRY RUN] Would initialize workspace with:")
        click.echo(f"    - Database: {db_url[:30]}..." if db_url else "    - Database: (not set)")
        click.echo(f"    - Schema: {schema}")
    else:
        # Generate display name
        if not display_name:
            import socket

            hostname = socket.gethostname().split(".")[0]
            import time

            display_name = f"{hostname}-{int(time.time())}"

        # Set env for initialization (only when using PostgreSQL)
        if db_url:
            os.environ["ENGRAM_DB_URL"] = db_url
        else:
            os.environ.pop("ENGRAM_DB_URL", None)

        async def init_workspace():
            # Import server to get engram_init
            from engram.server import engram_init

            # Call engram_init - this will initialize the workspace
            result = await engram_init(
                anonymous_mode=False,
                anon_agents=False,
                schema=schema,
            )
            return result

        result = asyncio.run(init_workspace())

        if result.get("status") == "initialized":
            engram_id = result.get("engram_id", "unknown")
            click.echo(f"  ✓ Workspace initialized: {engram_id}")
            click.echo("  ✓ Invite key generated")
        else:
            click.echo(f"  ❌ Setup failed: {result.get('status')}")
            return

    # Step 4: Print invite key
    click.echo("\n[3/4] Invite Key")
    click.echo("-" * 40)
    if dry_run:
        click.echo("  ek_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    else:
        click.echo(f"  {result.get('invite_key')}")
    click.echo("-" * 40)
    click.echo("\nShare this with teammates!")

    # Step 5: Print CLAUDE.md snippet
    click.echo("\n[4/4] CLAUDE.md Snippet")
    click.echo("-" * 40)
    click.echo("Copy this to your project root as CLAUDE.md:")
    click.echo("")

    claude_snippet = f"""# CLAUDE.md - Project Context for Claude

This project uses Engram for team memory. Before starting work on any task:

1. Run `engram status` to check workspace connection
2. Run `engram query "<your task>"` to check what the team already knows

## Engram Workspace
- Team ID: {engram_id if not dry_run else "YOUR_TEAM_ID"}
- Schema: {schema}
"""
    click.echo(claude_snippet)
    click.echo("-" * 40)

    click.echo("\n✓ Setup complete!")
    click.echo("\nNext steps:")
    click.echo("  1. Restart your IDE")
    click.echo("  2. Run: engram verify")
    click.echo("  3. Start working with your team!\n")


# ── engram completion ─────────────────────────────────────────────────

_SHELL_CONFIGS = {
    "bash": ("~/.bashrc", 'eval "$(_ENGRAM_COMPLETE=bash_source engram)"'),
    "zsh": ("~/.zshrc", 'eval "$(_ENGRAM_COMPLETE=zsh_source engram)"'),
    "fish": (
        "~/.config/fish/completions/engram.fish",
        "_ENGRAM_COMPLETE=fish_source engram | source",
    ),
}


@main.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]), required=False)
def completion(shell: str | None) -> None:
    """Install shell tab-completion for engram.

    Detects your current shell automatically, or pass bash/zsh/fish
    explicitly. Appends the completion hook to your shell profile.

    \b
    Examples:
        engram completion          # auto-detect shell
        engram completion zsh      # explicit shell
    """
    import os

    if shell is None:
        current = os.environ.get("SHELL", "")
        if "zsh" in current:
            shell = "zsh"
        elif "fish" in current:
            shell = "fish"
        elif "bash" in current:
            shell = "bash"
        else:
            click.echo(f"Could not detect shell from $SHELL={current!r}.")
            click.echo("Please specify explicitly: engram completion bash|zsh|fish")
            raise SystemExit(1)

    config_path, snippet = _SHELL_CONFIGS[shell]

    if shell == "fish":
        # Fish completions go in a dedicated file, not appended to a profile
        target = Path(config_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(snippet + "\n")
        click.echo(f"Wrote fish completions to {target}")
    else:
        target = Path(config_path).expanduser()
        # Check if already installed
        if target.exists() and snippet in target.read_text():
            click.echo(f"Engram completions already installed in {config_path}")
            return
        with target.open("a") as f:
            f.write(f"\n# Engram shell completion\n{snippet}\n")
        click.echo(f"Appended completion hook to {config_path}")

    click.echo(f"Restart your shell or run: source {config_path}")


@main.command("export")
@click.option(
    "--format", type=click.Choice(["json", "markdown"]), default="json", help="Export format."
)
@click.option("--output", "-o", type=click.Path(), help="Output file (stdout if not specified).")
@click.option("--scope", help="Filter by scope prefix.")
def export_cmd(format: str, output: str | None, scope: str | None) -> None:
    """Export workspace facts to JSON or Markdown."""
    import os
    import urllib.request

    ws = None
    try:
        from engram.workspace import read_workspace

        ws = read_workspace()
    except Exception:
        pass

    if not ws:
        click.echo("Error: No workspace configured")
        return

    mcp_url = os.environ.get("ENGRAM_MCP_URL", "http://localhost:7474")
    base_url = mcp_url.replace("/mcp", "") if "/mcp" in mcp_url else mcp_url

    try:
        url = f"{base_url}/api/facts?scope={scope or ''}&limit=10000"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            facts = data.get("facts", [])

        from engram.export import build_json_export, build_markdown_export

        if format == "json":
            result = build_json_export(ws.engram_id, facts, [])
            content = json.dumps(result, indent=2)
        else:
            result = build_markdown_export(ws.engram_id, facts, [])
            content = result

        if output:
            with open(output, "w") as f:
                f.write(content)
            click.echo(f"Exported {len(facts)} facts to {output}")
        else:
            click.echo(content)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)


if __name__ == "__main__":
    main()
