# Windsurf Quickstart

Windsurf is Codeium's AI-powered code editor.

## Setup

### Option 1: Auto-install (Recommended)
```bash
curl -fsSL https://engram-us.com/install | sh
```

### Option 2: Manual Setup

1. Create or edit `~/.codeium/windsurf/mcp_config.json`:
```json
{
  "mcpServers": {
    "engram": {
      "serverUrl": "https://mcp.engram.app/mcp"
    }
  }
}
```

For local development:
```json
{
  "mcpServers": {
    "engram": {
      "serverUrl": "http://localhost:7474/mcp"
    }
  }
}
```

Note: Windsurf uses `serverUrl` (capital U), not `url`.

2. Restart Windsurf

## First Time Setup

1. Open a new chat in Windsurf
2. Tell it: `"Set up Engram for my team"` to create workspace
3. Or: `"Join Engram with key ek_live_..."` to join existing workspace

## Usage

Windsurf will automatically:
- Query team knowledge before working on code
- Commit discoveries to shared memory
- Detect conflicts between facts

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

- Check config: `cat ~/.codeium/windsurf/mcp_config.json`
- Note: uses `serverUrl` not `url`
- Restart Windsurf after config changes

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.