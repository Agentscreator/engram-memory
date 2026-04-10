# Zed Quickstart

Zed supports MCP and can use Engram through `context_servers`.

## Setup

### Option 1: Auto-install (Recommended)

```bash
curl -fsSL https://engram-us.com/install | sh
```

### Option 2: Manual Setup

Edit `~/.config/zed/settings.json` and add:

```json
{
  "context_servers": {
    "engram": {
      "url": "https://mcp.engram.app/mcp"
    }
  }
}
```

For local development:

```json
{
  "context_servers": {
    "engram": {
      "url": "http://localhost:7474/mcp"
    }
  }
}
```

Note: Zed uses `context_servers`, not `mcpServers`.

2. Restart Zed.

## First Time Setup

1. Open a new chat in Zed
2. Tell it: `"Set up Engram for my team"` to create a workspace
3. Or: `"Join Engram with key ek_live_..."` to join an existing workspace

## Usage

Zed will automatically:

- query team knowledge before working on code
- commit discoveries to shared memory
- detect conflicts between facts

## Verification

```bash
engram verify
```

## Troubleshooting

Check config:

```bash
cat ~/.config/zed/settings.json
```

Note: uses `context_servers`.

Restart Zed after config changes.

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.