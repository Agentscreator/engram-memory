# VS Code (Copilot) Quickstart

VS Code requires GitHub Copilot extension for MCP support.

## Setup

### Option 1: Auto-install (Recommended)
```bash
curl -fsSL https://engram-us.com/install | sh
```

### Option 2: Manual Setup

1. Create or edit `~/Library/Application Support/Code/User/mcp.json` (macOS)
   or `~/.config/Code/User/mcp.json` (Linux):

```json
{
  "servers": {
    "engram": {
      "type": "http",
      "url": "https://mcp.engram.app/mcp"
    }
  }
}
```

For local development:
```json
{
  "servers": {
    "engram": {
      "type": "http",
      "url": "http://localhost:7474/mcp"
    }
  }
}
```

2. Restart VS Code
3. Ensure GitHub Copilot extension is installed

## First Time Setup

1. Open a new chat (Ctrl+Shift+P → "Copilot: Chat")
2. Tell it: `"Set up Engram for my team"` to create a workspace
3. Or: `"Join Engram with key ek_live_..."` to join existing workspace

## Usage

With Copilot + Engram, your AI assistant will:
- Query team knowledge before starting tasks
- Commit important discoveries
- Detect conflicts in team knowledge

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

- Ensure GitHub Copilot is active
- Check MCP config path matches your OS
- Restart VS Code after config changes

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.