# Claude Desktop Quickstart

Claude Desktop uses a stdio bridge for remote MCP servers.

## Setup

### Option 1: Auto-install (Recommended)
```bash
curl -fsSL https://engram-memory.com/install | sh
```

The installer automatically sets up the mcp-remote bridge.

### Option 2: Manual Setup

1. Create/edit Claude Desktop config at:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "engram": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://www.engram-memory.com/mcp"]
    }
  }
}
```

For local development:
```json
{
  "mcpServers": {
    "engram": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:7474/mcp"]
    }
  }
}
```

2. Restart Claude Desktop

## First Time Setup

1. Start a new conversation
2. Tell it: `"Set up Engram for my team"` to create workspace
3. Or: `"Join Engram with key ek_live_..."` to join existing workspace

## Requirements

- Node.js installed (for npx)
- Internet connection (for remote) or local server running

## Verification

```bash
engram verify
```

## Troubleshooting

- Ensure Node.js is installed: `node --version`
- Check config at correct path for your OS
- Restart Claude Desktop after changes

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.