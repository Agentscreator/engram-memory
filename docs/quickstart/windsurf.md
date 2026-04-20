# Windsurf / Kiro

## If you're setting up Engram for your team

Run the installer once:

```bash
curl -fsSL https://engram-memory.com/install | sh
```

This writes the Engram MCP server to `~/.codeium/windsurf/mcp_config.json`
and adds Engram instructions to Kiro's steering documents.

Restart Windsurf, then ask your agent:

```
"Set up Engram for my team"
```

Share the invite link from the dashboard with your team.

## If you're joining a teammate's workspace

You don't need to install anything. Click the invite link your teammate
shared, sign in at [engram-memory.com](https://engram-memory.com), and
accept the workspace invite.

When you open the codebase, your agent reads `AGENTS.md` and `.engram.env`
from the repo and connects via the REST API automatically. Your messages
will be recorded in shared memory — this is what you agreed to when you
accepted the invite.

## Verification

Ask your agent: `"Am I connected to Engram? Check .engram.env and query the API."`

## Note on MCP

Windsurf uses `serverUrl` (capital U) in its MCP config:

```json
{
  "mcpServers": {
    "engram": {
      "serverUrl": "https://www.engram-memory.com/mcp"
    }
  }
}
```

The installer handles this automatically.

## Troubleshooting

- Check config: `cat ~/.codeium/windsurf/mcp_config.json`
- Restart Windsurf after config changes
- Full guide: [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md)
