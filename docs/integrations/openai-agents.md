# OpenAI Agents SDK Integration

Engram can be used from OpenAI Agents SDK workflows through function tools backed by
the Engram HTTP API. This does not require MCP.

Start a local Engram HTTP server:

```bash
engram serve --http
```

Install the OpenAI Agents SDK in the application that will run the agent:

```bash
pip install openai-agents
```

## Usage

```python
from agents import Agent, Runner

from engram.integrations.openai_agents import create_engram_tools


tools = create_engram_tools(
    base_url="http://127.0.0.1:7474",
    api_key="ek_live_YOUR_INVITE_KEY",
    default_scope="auth",
)

agent = Agent(
    name="Engram-aware agent",
    instructions=(
        "Query Engram before making architecture decisions. "
        "Commit only verified discoveries, decisions, and corrections."
    ),
    tools=tools,
)

Runner.run_sync(agent, "What do we know about auth?")
```

The integration exposes three tools:

| Tool | Purpose |
|---|---|
| `engram_query` | Read verified workspace facts relevant to a topic |
| `engram_commit` | Commit a verified fact to Engram |
| `engram_conflicts` | Review open or resolved conflicts before important decisions |

## Memory Model

The OpenAI Agents SDK `Session` memory stores conversation turns. Engram stores
verified shared workspace facts. Keep those responsibilities separate:

- use SDK sessions for short-term conversation history
- use Engram for durable team knowledge that should survive across agents and sessions
- do not commit raw chat transcripts to Engram

## Without an Invite Key

For local development without auth:

```python
tools = create_engram_tools(base_url="http://127.0.0.1:7474")
```

For team mode, pass the invite key as `api_key`; it is sent as a Bearer token to
Engram's REST API.
