# Cursor Quickstart

Cursor is a VS Code fork by Anysphere with built-in AI assistance.
Engram connects to Cursor through MCP as a hosted remote server.

## Setup

### Option 1: Auto-install (Recommended)
```bash
curl -fsSL https://engram-memory.com/install | sh
```

The installer writes Engram to your global Cursor MCP config at
`~/.cursor/mcp.json`, then writes Cursor rules so the agent knows to call
`engram_status` first in new sessions.

### Option 2: Manual Setup

1. Create or edit your global Cursor MCP config at `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "engram": {
      "url": "https://www.engram-memory.com/mcp"
    }
  }
}
```

If an older Engram config uses `command` and `args` with `uvx`, re-run
`engram install`. The installer migrates the exact old Engram Cursor entry to
the hosted `url` form above. Custom Cursor entries are left unchanged.

Cursor also supports project-level MCP config at `.cursor/mcp.json`. Use that
only when you want the Engram server config checked into a specific repository.
For most users, the global `~/.cursor/mcp.json` file is the right default.

For local development:
```json
{
  "mcpServers": {
    "engram": {
      "url": "http://localhost:7474/mcp"
    }
  }
}
```

Only use the local URL after starting Engram locally:

```bash
python -m engram.cli serve --http
```

2. Restart Cursor

## First Time Setup

1. Open a new chat in Cursor Agent mode
2. Tell it: `"Set up Engram for my team"` to create a workspace
3. Or: `"Join Engram with key ek_live_..."` to join an existing workspace

## Usage

Once configured, Cursor's AI will:
- Query team knowledge before working on code
- Commit important discoveries automatically
- Detect and surface conflicts between facts

## Verification

```bash
engram verify
```

**In your IDE:** Ask your agent: "Call engram_status and tell me what it returns."

Expected output:
```
{"status": "ready", "mode": "team", "engram_id": "ENG-XXXXXX", "schema": "engram"}
```

## Troubleshooting

- Check config: `cat ~/.cursor/mcp.json`
- Confirm the entry is under `mcpServers.engram.url`
- If the entry still uses `command: "uvx"`, re-run `engram install` or replace it
  with the hosted `url` entry above
- Check Cursor's MCP/tools UI and confirm Engram is enabled
- Approve Cursor's MCP tool call prompt when it asks to run `engram_status`
- Restart Cursor after making changes
- Ensure port 7474 is available if using local server
- If Cursor searches files instead of calling `engram_status`, reload the MCP server
  or restart Cursor and try the explicit prompt above

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.
