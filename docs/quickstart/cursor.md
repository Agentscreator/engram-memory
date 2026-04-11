# Cursor Quickstart

Cursor is a VS Code fork by Anysphere with built-in AI assistance.

## Setup

### Option 1: Auto-install (Recommended)
```bash
curl -fsSL https://engram-us.com/install | sh
```

### Option 2: Manual Setup

1. Create or edit `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "engram": {
      "url": "https://mcp.engram.app/mcp"
    }
  }
}
```

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

2. Restart Cursor

## First Time Setup

1. Open a new chat in Cursor
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
- Restart Cursor after making changes
- Ensure port 7474 is available if using local server

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.