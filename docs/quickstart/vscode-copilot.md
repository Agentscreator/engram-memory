# VS Code Agent Mode (GitHub Copilot) Quickstart

VS Code Agent Mode supports MCP servers through GitHub Copilot. Engram works as a
remote HTTP MCP server and does not require a local stdio bridge for VS Code.

## Setup

### Option 1: Auto-install (Recommended)
```bash
curl -fsSL https://engram-memory.com/install | sh
```

### Option 2: Manual Setup

1. Create or edit your VS Code user-profile `mcp.json`:
   - macOS: `~/Library/Application Support/Code/User/mcp.json`
   - Linux: `~/.config/Code/User/mcp.json`
   - Windows: `%APPDATA%\Code\User\mcp.json`

```json
{
  "servers": {
    "engram": {
      "type": "http",
      "url": "https://www.engram-memory.com/mcp"
    }
  }
}
```

VS Code also supports workspace MCP config at `.vscode/mcp.json`. Use the user-profile
file for Engram if you want it available across all workspaces.

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
4. If VS Code prompts you to trust the MCP server, approve Engram after reviewing the
   server URL.

## First Time Setup

1. Open Chat in Agent Mode.
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
- Confirm Agent Mode is enabled in Chat
- Check MCP config path matches your OS
- Confirm the Engram entry is under `servers.engram`
- Restart VS Code after config changes
- Use VS Code's MCP output log if the server appears but does not start

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.
