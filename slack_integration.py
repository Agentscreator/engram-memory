"""Slack Bot Integration for Engram (Issue #40)

Allows querying and committing facts directly from Slack.

Usage:
    /engram query <search>    - Search facts
    /engram commit <fact>    - Commit a fact

Setup:
    1. Create a Slack app at https://api.slack.com/apps
    2. Add Bot Token and Signing Secret to environment
    3. Run this server or deploy to Lambda
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="Engram Slack Bot")


class SlackCommand(BaseModel):
    """Slack slash command payload."""

    command: str
    text: str
    user_id: str
    channel_id: str
    response_url: str


class SlackMessage(BaseModel):
    """Response message for Slack."""

    response_type: str = "in_channel"
    text: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/slack/engram")
async def slack_engram(cmd: SlackCommand):
    """Handle /engram slash command from Slack."""
    parts = cmd.text.strip().split(maxsplit=1)
    if not parts:
        return SlackMessage(text="Usage: /engram query <search> or /engram commit <fact>")

    action = parts[0].lower()
    query = parts[1] if len(parts) > 1 else ""

    if action == "query":
        return await handle_query(query)
    elif action == "commit":
        return await handle_commit(query, cmd.user_id)
    elif action == "conflicts":
        return await handle_conflicts()
    else:
        return SlackMessage(text=f"Unknown action: {action}. Use: query, commit, or conflicts")


async def handle_query(query: str) -> SlackMessage:
    """Search facts and return results."""
    import urllib.request
    import urllib.parse
    import json
    import os

    server_url = os.environ.get("ENGRAM_SERVER_URL", "http://localhost:7474")
    api_url = f"{server_url}/api/query?topic={urllib.parse.quote(query)}"

    try:
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)

        facts = data.get("facts", [])
        if not facts:
            return SlackMessage(text=f"No facts found for: {query}")

        result = f"Found {len(facts)} fact(s) for '{query}':\n"
        for f in facts[:5]:
            result += f"• {f.get('content', '')[:100]}\n"
        return SlackMessage(text=result)
    except Exception as e:
        return SlackMessage(text=f"Error: {str(e)}")


async def handle_commit(fact: str, user_id: str) -> SlackMessage:
    """Commit a new fact."""
    import urllib.request
    import json
    import os

    server_url = os.environ.get("ENGRAM_SERVER_URL", "http://localhost:7474")
    api_url = f"{server_url}/api/commit"

    try:
        data = {
            "content": fact,
            "agent_id": f"slack-{user_id}",
            "confidence": 0.9,
        }
        req = urllib.request.Request(
            api_url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.load(resp)

        if result.get("fact_id"):
            return SlackMessage(text=f"✓ Committed: {fact[:80]}")
        else:
            return SlackMessage(text=f"Error: {result.get('error', 'Unknown error')}")
    except Exception as e:
        return SlackMessage(text=f"Error: {str(e)}")


async def handle_conflicts() -> SlackMessage:
    """Get open conflicts."""
    import urllib.request
    import json
    import os

    server_url = os.environ.get("ENGRAM_SERVER_URL", "http://localhost:7474")
    api_url = f"{server_url}/api/conflicts?status=open"

    try:
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            conflicts = json.load(resp)

        if not conflicts:
            return SlackMessage(text="✓ No open conflicts")

        result = f"⚠️  {len(conflicts)} open conflict(s):\n"
        for c in conflicts[:5]:
            result += f"• {c.get('explanation', 'Conflict')[:80]}\n"
        return SlackMessage(text=result)
    except Exception as e:
        return SlackMessage(text=f"Error: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "7475"))
    uvicorn.run(app, host="0.0.0.0", port=port)
