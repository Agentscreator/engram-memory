# Supported IDEs

Engram's install script (`curl -fsSL https://engram-memory.com/install | sh`) auto-detects and configures the following IDEs. Each IDE has its own MCP config format — the installer handles the differences automatically.

By default, the installer writes `https://www.engram-memory.com/mcp` into each MCP config. If you need a custom endpoint, set `ENGRAM_MCP_URL` before running the installer.

## Auto-configured by the installer

| IDE | Config file | Remote MCP format | Notes |
|-----|------------|-------------------|-------|
| **Claude Code** | `~/.claude.json` | `mcpServers.{type: "http", url}` | CLI agent by Anthropic |
| **Claude Desktop** | `claude_desktop_config.json` | `npx mcp-remote` stdio bridge | No native remote URL support; installer uses [mcp-remote](https://www.npmjs.com/package/mcp-remote) as a bridge. Requires Node.js/npx. |
| **Cursor** | `~/.cursor/mcp.json` | `mcpServers.{url}` | VS Code fork by Anysphere |
| **VS Code Agent Mode** | `Code/User/mcp.json` | `servers.{type: "http", url}` | Requires GitHub Copilot with Agent Mode |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` | `mcpServers.{serverUrl}` | Uses `serverUrl` key, not `url` |
| **Kiro** | `~/.kiro/settings/mcp.json` | `mcpServers.{url}` | By AWS |
| **Zed** | `settings.json` | `context_servers.{url}` | Rust-based editor; uses `context_servers` key |
| **Amazon Q Developer** | `~/.aws/amazonq/mcp.json` | `mcpServers.{url}` | AWS CLI + IDE agent |
| **Trae** | `<App Support>/Trae/User/mcp.json` | `mcpServers.{url}` | VS Code fork by ByteDance |
| **JetBrains / Junie** | `~/.junie/mcp/mcp.json` | `mcpServers.{url}` | IntelliJ, PyCharm, WebStorm, etc. |
| **Cline** | `~/Documents/Cline/MCP/cline_mcp_settings.json` | `mcpServers.{url}` | VS Code extension |
| **Roo Code** | VS Code `globalStorage/.../cline_mcp_settings.json` | `mcpServers.{url}` | Cline fork with multi-persona agents |
| **OpenCode** | `~/.config/opencode/config.json` | `mcp.{type: "remote", url}` | CLI agent by SST |

## Manual setup required

These IDEs support MCP but can't be auto-configured by the installer.

| IDE | Why | How to add Engram manually |
|-----|-----|---------------------------|
| **OpenAI Codex** | TOML config, stdio-only (no remote HTTP) | Not currently possible. Codex doesn't support remote MCP servers. A local stdio proxy is needed. |
| **PearAI** | Config path undocumented | Likely similar to Cursor. Try adding to `~/.pearai/mcp.json` with `mcpServers.{url}` format. |
| **Google Antigravity** | Cloud-based IDE, no local config | Add via the Antigravity UI if it supports custom MCP servers. |

## No MCP support

| IDE | Status |
|-----|--------|
| **Aider** | Uses its own tool integration model. No MCP support. |

## Adding Engram manually

If your IDE isn't listed above but supports MCP, add Engram as a remote HTTP server:

**URL:**
```
https://www.engram-memory.com/mcp
```

**With an invite key:**
```json
{
  "url": "https://www.engram-memory.com/mcp",
  "headers": {
    "Authorization": "Bearer YOUR_INVITE_KEY"
  }
}
```

Adapt the key names to match your IDE's format (`url`, `serverUrl`, `type`, etc.) and restart your IDE.

## Platform-specific install commands

**macOS / Linux:**
```bash
curl -fsSL https://engram-memory.com/install | sh
```

**Windows PowerShell:**
```powershell
irm https://engram-memory.com/install.ps1 | iex
```

**Windows CMD:**
```cmd
curl -fsSL https://engram-memory.com/install.cmd -o install.cmd && install.cmd && del install.cmd
```

To join an existing workspace:
```bash
curl -fsSL https://engram-memory.com/install | sh -s -- --join ek_live_YOUR_KEY
```
## Verification and troubleshooting

After installation:

1. Restart or reload your IDE if it was already open.
2. Confirm that Engram was added to the IDE's MCP config file:
   - Cursor: `~/.cursor/mcp.json`
   - VS Code Agent Mode: `Code/User/mcp.json`
   - Claude Code: `~/.claude.json`
3. Open your IDE's MCP or tools UI, if available, and confirm the Engram server appears and is enabled.
4. If you are joining an existing workspace, use your invite key during install.

Opening the MCP endpoint directly in a browser is not a reliable verification step. Verify the integration through your IDE's MCP config and tool or server UI instead.

### Expected install output

Install output varies by platform and by which IDEs are present on the machine. A typical successful run looks like this:

```text
Do you have an invite key from a teammate? (y/n):
Detecting MCP clients...
  ✓ /path/to/your/mcp.json

Done! Restart your IDE, then ask your agent:

  "Set up Engram for my team"    — to create a new workspace
  "Join Engram with key ek_live_..."  — to join a teammate's workspace
```

If you install with `--join`, the final line will instead look like:

```text
"Set up Engram"  — your agent will connect to your workspace
```

### Cursor
**Common failure:** Cursor was not restarted after installation, or the agent searches files instead of calling the Engram MCP tool.
**Fix:** Confirm Engram is under `mcpServers.engram.url` in `~/.cursor/mcp.json`, restart Cursor, approve the MCP tool prompt if shown, and confirm Engram is enabled in Cursor's MCP/tools UI. If Engram still uses the old `command: "uvx"` entry, re-run `engram install` to migrate the exact legacy entry to the hosted URL form.

### VS Code
**Common failure:** VS Code uses `servers.engram`, not `mcpServers.engram`.  
**Fix:** Confirm Engram was written under `servers` in `Code/User/mcp.json`, then restart VS Code and approve the MCP server trust prompt if shown.

### Claude Code
**Common failure:** Claude Code and Claude Desktop use different config files and setup methods.  
**Fix:** Check `~/.claude.json`, confirm Engram is listed under `mcpServers.engram`, then restart Claude Code.
