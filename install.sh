#!/bin/sh
# Engram installer — adds Engram to your MCP config
# Usage: curl -fsSL https://engram-memory.com/install | sh
#   or:  curl -fsSL https://engram-memory.com/install | sh -s -- --join ek_live_...

set -e

MCP_URL="${ENGRAM_MCP_URL:-https://mcp.engram.app/mcp}"
INVITE_KEY=""

# Parse --join flag
while [ $# -gt 0 ]; do
  case "$1" in
    --join) INVITE_KEY="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# ── Detect OS ──────────────────────────────────────────────────────
OS="$(uname -s)"
if [ "$OS" != "Darwin" ] && [ "$OS" != "Linux" ]; then
  echo "Unsupported OS: $OS"
  echo "Manually add Engram to your MCP config:"
  echo "  url: $MCP_URL"
  exit 1
fi

# ── Require Python 3 ───────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required but not found. Please install it first."
  exit 1
fi

# ── Ask for invite key if not provided ─────────────────────────────
if [ -z "$INVITE_KEY" ]; then
  printf "\nDo you have an invite key from a teammate? (y/n): "
  read HAS_KEY
  if [ "$HAS_KEY" = "y" ] || [ "$HAS_KEY" = "Y" ]; then
    printf "Paste your invite key: "
    read INVITE_KEY
  fi
fi

# ── Write shared Python patcher to a temp file ─────────────────────
PATCHER="$(mktemp /tmp/engram_patch.XXXXXX.py)"
trap 'rm -f "$PATCHER"' EXIT

cat > "$PATCHER" << 'PYEOF'
import json, sys, os

def load(path):
    if not os.path.exists(path):
        return {}
    try:
        raw = open(path).read().strip()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}

fmt, f, u, k = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
c = load(f)
d = os.path.dirname(f)
if d:
    os.makedirs(d, exist_ok=True)

if fmt == "url":          # Cursor, Kiro, Trae, Amazon Q, JetBrains, Cline, Roo
    c.setdefault("mcpServers", {})
    e = {"url": u}
    if k: e["headers"] = {"Authorization": f"Bearer {k}"}
    c["mcpServers"]["engram"] = e
elif fmt == "windsurf":   # uses serverUrl instead of url
    c.setdefault("mcpServers", {})
    e = {"serverUrl": u}
    if k: e["headers"] = {"Authorization": f"Bearer {k}"}
    c["mcpServers"]["engram"] = e
elif fmt == "vscode":     # {servers: {type: "http", url}}
    c.setdefault("servers", {})
    e = {"type": "http", "url": u}
    if k: e["headers"] = {"Authorization": f"Bearer {k}"}
    c["servers"]["engram"] = e
elif fmt == "claude-code":  # {type: "http", url} in mcpServers
    c.setdefault("mcpServers", {})
    e = {"type": "http", "url": u}
    if k: e["headers"] = {"Authorization": f"Bearer {k}"}
    c["mcpServers"]["engram"] = e
elif fmt == "claude-desktop":  # npx mcp-remote bridge
    c.setdefault("mcpServers", {})
    a = ["-y", "mcp-remote@latest", u]
    if k: a.extend(["--header", f"Authorization: Bearer {k}"])
    c["mcpServers"]["engram"] = {"command": "npx", "args": a}
elif fmt == "opencode":   # {mcp: {type: "remote", url}}
    c.setdefault("mcp", {})
    e = {"type": "remote", "url": u, "enabled": True}
    if k: e["headers"] = {"Authorization": f"Bearer {k}"}
    c["mcp"]["engram"] = e
elif fmt == "zed":        # {context_servers: {url}}
    c.setdefault("context_servers", {})
    e = {"url": u}
    if k: e["headers"] = {"Authorization": f"Bearer {k}"}
    c["context_servers"]["engram"] = e

json.dump(c, open(f, "w"), indent=2)
print(f"  ✓ {f}")
PYEOF

patch() { python3 "$PATCHER" "$1" "$2" "$MCP_URL" "$INVITE_KEY"; }

# ── Detect and patch MCP clients ──────────────────────────────────
echo ""
echo "Detecting MCP clients..."
PATCHED=0

# Claude Desktop — npx mcp-remote bridge
if [ "$OS" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Claude" ]; then
  patch claude-desktop "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  PATCHED=$((PATCHED + 1))
fi
if [ "$OS" = "Linux" ] && [ -d "$HOME/.config/Claude" ]; then
  patch claude-desktop "$HOME/.config/Claude/claude_desktop_config.json"
  PATCHED=$((PATCHED + 1))
fi

# Claude Code — {type: "http", url} in ~/.claude.json
if [ -f "$HOME/.claude.json" ] || [ -d "$HOME/.claude" ]; then
  patch claude-code "$HOME/.claude.json"
  PATCHED=$((PATCHED + 1))
fi

# Cursor
if [ -f "$HOME/.cursor/mcp.json" ] || [ -d "$HOME/.cursor" ]; then
  patch url "$HOME/.cursor/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# VS Code — {servers: {type: "http", url}} in mcp.json
if [ "$OS" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Code" ]; then
  patch vscode "$HOME/Library/Application Support/Code/User/mcp.json"
  PATCHED=$((PATCHED + 1))
fi
if [ "$OS" = "Linux" ] && [ -d "$HOME/.config/Code" ]; then
  patch vscode "$HOME/.config/Code/User/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# Windsurf — uses serverUrl
if [ -f "$HOME/.codeium/windsurf/mcp_config.json" ] || [ -d "$HOME/.codeium/windsurf" ]; then
  patch windsurf "$HOME/.codeium/windsurf/mcp_config.json"
  PATCHED=$((PATCHED + 1))
fi

# Kiro
if [ -f "$HOME/.kiro/settings/mcp.json" ] || [ -d "$HOME/.kiro" ]; then
  patch url "$HOME/.kiro/settings/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# Zed — {context_servers: {url}}
if [ "$OS" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Zed" ]; then
  patch zed "$HOME/Library/Application Support/Zed/settings.json"
  PATCHED=$((PATCHED + 1))
fi
if [ "$OS" = "Linux" ] && [ -d "$HOME/.config/zed" ]; then
  patch zed "$HOME/.config/zed/settings.json"
  PATCHED=$((PATCHED + 1))
fi

# Amazon Q Developer
if [ -d "$HOME/.aws/amazonq" ]; then
  patch url "$HOME/.aws/amazonq/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# Trae (ByteDance)
if [ "$OS" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Trae" ]; then
  patch url "$HOME/Library/Application Support/Trae/User/mcp.json"
  PATCHED=$((PATCHED + 1))
fi
if [ "$OS" = "Linux" ] && [ -d "$HOME/.config/Trae" ]; then
  patch url "$HOME/.config/Trae/User/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# JetBrains / Junie
if [ -d "$HOME/.junie" ]; then
  patch url "$HOME/.junie/mcp/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# Cline (VS Code extension)
CLINE_DIR="$HOME/Documents/Cline/MCP"
if [ -d "$CLINE_DIR" ] || [ -d "$HOME/Documents/Cline" ]; then
  patch url "$CLINE_DIR/cline_mcp_settings.json"
  PATCHED=$((PATCHED + 1))
fi

# Roo Code (VS Code extension, Cline fork)
if [ "$OS" = "Darwin" ]; then
  ROO_STORAGE="$HOME/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline"
else
  ROO_STORAGE="$HOME/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline"
fi
if [ -d "$ROO_STORAGE" ]; then
  patch url "$ROO_STORAGE/settings/cline_mcp_settings.json"
  PATCHED=$((PATCHED + 1))
fi

# OpenCode — {mcp: {type: "remote", url}}
if [ -d "$HOME/.config/opencode" ] || [ -f "$HOME/.config/opencode/config.json" ]; then
  patch opencode "$HOME/.config/opencode/config.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Result ─────────────────────────────────────────────────────────
echo ""
if [ "$PATCHED" -eq 0 ]; then
  echo "No MCP clients detected. Manually add to your IDE's MCP config:"
  echo ""
  echo "  Remote MCP URL: $MCP_URL"
  if [ -n "$INVITE_KEY" ]; then
    echo "  Header: Authorization: Bearer $INVITE_KEY"
  fi
  echo ""
  echo "Then restart your IDE."
else
  echo "Done! Restart your IDE, then ask your agent:"
  if [ -z "$INVITE_KEY" ]; then
    echo ""
    echo "  \"Set up Engram for my team\"    — to create a new workspace"
    echo "  \"Join Engram with key ek_live_...\"  — to join a teammate's workspace"
  else
    echo ""
    echo "  \"Set up Engram\"  — your agent will connect to your workspace"
  fi
fi
echo ""
