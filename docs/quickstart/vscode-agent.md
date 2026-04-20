# VS Code Agent Mode Quickstart

VS Code's Agent Mode (available since early 2026) supports MCP and is a massive distribution channel for Engram.

## Requirements

- VS Code 1.99+ with Agent Mode enabled
- Or VS Code Insiders with Agent Mode

## Setup

### Option 1: Auto-install (Recommended)
```bash
curl -fsSL https://engram-us.com/install | sh
```

### Option 2: Manual Setup

1. Open VS Code Settings (`.vscode/mcp.json` or global):
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

2. Enable Agent Mode:
   - Open VS Code Command Palette (Ctrl+Shift+P)
   - Type: "Agent Mode: Enable" or enable in Settings

3. Restart VS Code

## First Time Setup

1. Open a new chat in Agent Mode
2. Tell the agent: "Set up Engram for my team" to create a workspace
3. Or: "Join Engram with key ek_live_..." to join existing workspace

## Agent Mode Specific Features

The agent can now:
- **Query team knowledge** before working on code
- **Commit discoveries** automatically
- **Detect conflicts** between facts
- **Use all Engram MCP tools**:
  - `engram_status()` - Check setup
  - `engram_query()` - Search facts
  - `engram_commit()` - Commit facts
  - `engram_conflicts()` - View conflicts
  - `engram_resolve()` - Resolve conflicts

## Verification

```bash
engram verify
```

**In VS Code:**
Ask the agent: "Call engram_status and tell me what it returns."

Expected output:
```json
{
  "status": "ready", 
  "mode": "team", 
  "engram_id": "ENG-XXXXXX", 
  "schema": "engram"
}
```

## Testing Agent Mode Integration

1. Ask the agent to find something in the codebase
2. Ask: "What does the team know about API config?"
3. The agent should query Engram automatically

## Known Issues

- Agent Mode MCP support is newer - restart if tools don't appear
- Some agents may not call tools automatically - explicitly prompt them

## Troubleshooting

- Check config: `cat ~/.vscode/mcp.json`
- Restart VS Code after making changes
- Ensure port 7474 is available for local server

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.