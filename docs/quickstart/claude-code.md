# Claude Code Quickstart

Claude Code is Anthropic's CLI agent. Engram integrates seamlessly.

## Setup

### Option 1: Auto-install (Recommended)
```bash
curl -fsSL https://engram-us.com/install | sh
```

### Option 2: Manual Setup

1. Create or edit `~/.claude.json`:
```json
{
  "mcpServers": {
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
  "mcpServers": {
    "engram": {
      "type": "http", 
      "url": "http://localhost:7474/mcp"
    }
  }
}
```

2. Restart Claude Code

## First Time Setup

After starting a new Claude Code session:

1. Claude Code will automatically detect Engram
2. Tell it: `"Set up Engram for my team"` to create a workspace
3. Or: `"Join Engram with key ek_live_..."` to join an existing workspace

## Usage

Once configured, Claude Code will:
- Query team memory before starting work on any task
- Commit important discoveries to shared memory
- Detect and help resolve conflicts

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

- Check config: `cat ~/.claude.json`
- Restart Claude Code after config changes
- Ensure Engram is running if using local server

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.