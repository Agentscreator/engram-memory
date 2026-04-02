"""CLI entry point for Engram.

Usage:
    engram serve                    # stdio (default, for MCP clients)
    engram serve --http             # Streamable HTTP on localhost:7474
    engram serve --http --auth      # team mode with JWT auth
    engram token create --engineer alice@example.com
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

from engram.storage import DEFAULT_DB_PATH


@click.group()
def main() -> None:
    """Engram - Multi-agent memory consistency for engineering teams."""
    pass


@main.command()
@click.option("--http", is_flag=True, help="Streamable HTTP transport.")
@click.option("--host", default="127.0.0.1", help="Host to bind.")
@click.option("--port", default=7474, type=int, help="Port to bind.")
@click.option("--db", default=str(DEFAULT_DB_PATH), help="SQLite path.")
@click.option("--log-level", default="INFO", help="Logging level.")
@click.option("--auth", is_flag=True, help="Enable JWT auth (team mode).")
@click.option("--rate-limit", default=50, type=int, help="Commits/agent/hr.")
def serve(
    http: bool, host: str, port: int, db: str, log_level: str,
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
    http: bool, host: str, port: int, db_path: str, logger: logging.Logger,
    auth_enabled: bool = False, rate_limit: int = 50,
) -> None:
    from engram.engine import EngramEngine
    from engram.server import mcp, set_rate_limiter, set_auth_enabled
    import engram.server as server_module
    from engram.storage import Storage

    storage = Storage(db_path=db_path)
    await storage.connect()
    logger.info("Database: %s", db_path)

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
    logger.info("Detection worker started")

    expired = await storage.expire_ttl_facts()
    if expired:
        logger.info("Expired %d TTL facts on startup", expired)

    try:
            logger.info("Starting Streamable HTTP on %s:%d", host, port)
            logger.info("Home: http://%s:%d/", host, port)
            logger.info("Dashboard: http://%s:%d/dashboard", host, port)
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
