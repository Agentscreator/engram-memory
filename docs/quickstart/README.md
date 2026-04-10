# Per-IDE Quickstart Guides

This directory contains step-by-step setup guides for using Engram with different IDEs and AI assistants.

## Quick Links

| IDE | Guide | Status |
|-----|-------|--------|
| Claude Code | [claude-code.md](./claude-code.md) | ✓ Complete |
| Cursor | [cursor.md](./cursor.md) | ✓ Complete |
| VS Code (Copilot) | [vscode-copilot.md](./vscode-copilot.md) | ✓ Complete |
| Claude Desktop | [claude-desktop.md](./claude-desktop.md) | ✓ Complete |
| Windsurf | [windsurf.md](./windsurf.md) | ✓ Complete |
| Zed | [zed.md](./zed.md) | ✓ Complete |

## General Setup (All IDEs)

All IDEs follow the same basic pattern:

1. **Run the installer**
   ```bash
   curl -fsSL https://engram-us.com/install | sh
   ```

2. **Restart your IDE**

3. **Ask your agent to set up Engram**
   ```
   "Set up Engram for my team"
   ```

4. **Or join an existing workspace**
   ```
   "Join Engram with key ek_live_..."
   ```

## Running Locally

If you want to use a local Engram server instead of the hosted version:

1. **Start Engram server**
   ```bash
   cd /path/to/Engram
   source .venv/bin/activate
   python -m engram.cli serve --http
   ```

2. **Configure your IDE** to use `http://localhost:7474/mcp` instead of the default URL

3. **Restart your IDE**

## Troubleshooting

If your IDE doesn't detect Engram:
- Check the MCP config file for your IDE
- Verify Engram is running: `curl http://localhost:7474/`
- Run `engram verify` to check configuration

See [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md) for more help.