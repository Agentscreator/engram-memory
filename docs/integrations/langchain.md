# LangChain / LangGraph Integration

Engram can be used from LangChain and LangGraph workflows through the HTTP API.
This does not require MCP.

Start a local Engram HTTP server:

```bash
engram serve --http
```

## REST Client

Use the lightweight client when you want direct control from any Python pipeline:

```python
from engram.client import EngramClient

client = EngramClient(base_url="http://127.0.0.1:7474")

facts = client.query("How does auth work?", scope="auth")
client.commit(
    "Auth uses JWT session tokens",
    scope="auth",
    confidence=0.9,
    provenance="docs/auth.md",
)
```

## LangChain Memory

Install LangChain's core package if your environment does not already include it:

```bash
pip install langchain-core
```

Then use `EngramMemory` as a LangChain memory object:

```python
from engram.integrations.langchain import EngramMemory

memory = EngramMemory(
    base_url="http://127.0.0.1:7474",
    scope="auth",
    memory_key="engram_memory",
)

context = memory.load_memory_variables({"input": "How does auth work?"})
print(context["engram_memory"])
```

`EngramMemory` reads relevant workspace facts into the chain context. It does
not automatically commit chat transcripts. Commit only verified facts:

```python
memory.commit_fact(
    "The auth service validates JWTs on every request",
    scope="auth",
    confidence=0.9,
)
```

## LangGraph

LangGraph has its own checkpointing and persistence model. For v1, use the
Engram REST client inside graph nodes when a node needs team memory:

```python
from engram.client import EngramClient

client = EngramClient(base_url="http://127.0.0.1:7474")


def retrieve_team_memory(state):
    facts = client.query(state["task"], scope=state.get("scope"), limit=5)
    return {"engram_memory": facts}
```

Keep checkpoint state and Engram memory separate: checkpoints store graph state;
Engram stores verified team facts.
