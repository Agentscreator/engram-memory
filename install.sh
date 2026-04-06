#!/bin/sh
# Engram installer — adds Engram to your MCP config
# Usage: curl -fsSL https://engram-us.com/install | sh
#   or:  curl -fsSL https://engram-us.com/install | sh -s -- --join ek_live_...

set -e

MCP_URL="https://www.engram-us.com/mcp"
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

# ── Per-IDE JSON patchers ──────────────────────────────────────────
# Each IDE has its own config format. We use Python to patch each correctly.

# mcpServers.engram = {url, headers?}
# Used by: Cursor, Kiro, Trae, Amazon Q
patch_mcpservers_url() {
  python3 - "$1" "$MCP_URL" "$INVITE_KEY" << 'PYEOF'
import json, sys, os
f, u, k = sys.argv[1], sys.argv[2], sys.argv[3]

def load_json_or_empty(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            raw = fh.read().strip()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}

c = load_json_or_empty(f)
os.makedirs(os.path.dirname(f), exist_ok=True)
c.setdefault("mcpServers", {})
e = {"url": u}
if k: e["headers"] = {"Authorization": f"Bearer {k}"}
c["mcpServers"]["engram"] = e
json.dump(c, open(f, "w"), indent=2)
print(f"  ✓ {f}")
PYEOF
}

# Windsurf: mcpServers.engram = {serverUrl, headers?}
patch_windsurf() {
  python3 - "$1" "$MCP_URL" "$INVITE_KEY" << 'PYEOF'
import json, sys, os
f, u, k = sys.argv[1], sys.argv[2], sys.argv[3]
def load_json_or_empty(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            raw = fh.read().strip()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
c = load_json_or_empty(f)
os.makedirs(os.path.dirname(f), exist_ok=True)
c.setdefault("mcpServers", {})
e = {"serverUrl": u}
if k: e["headers"] = {"Authorization": f"Bearer {k}"}
c["mcpServers"]["engram"] = e
json.dump(c, open(f, "w"), indent=2)
print(f"  ✓ {f}")
PYEOF
}

# VS Code: servers.engram = {type: "http", url, headers?}
patch_vscode() {
  python3 - "$1" "$MCP_URL" "$INVITE_KEY" << 'PYEOF'
import json, sys, os
f, u, k = sys.argv[1], sys.argv[2], sys.argv[3]
def load_json_or_empty(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            raw = fh.read().strip()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
c = load_json_or_empty(f)
os.makedirs(os.path.dirname(f), exist_ok=True)
c.setdefault("servers", {})
e = {"type": "http", "url": u}
if k: e["headers"] = {"Authorization": f"Bearer {k}"}
c["servers"]["engram"] = e
json.dump(c, open(f, "w"), indent=2)
print(f"  ✓ {f}")
PYEOF
}

# Claude Code: mcpServers.engram = {type: "http", url, headers?} in ~/.claude.json
patch_claude_code() {
  python3 - "$1" "$MCP_URL" "$INVITE_KEY" << 'PYEOF'
import json, sys, os
f, u, k = sys.argv[1], sys.argv[2], sys.argv[3]
def load_json_or_empty(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            raw = fh.read().strip()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
c = load_json_or_empty(f)
c.setdefault("mcpServers", {})
e = {"type": "http", "url": u}
if k: e["headers"] = {"Authorization": f"Bearer {k}"}
c["mcpServers"]["engram"] = e
json.dump(c, open(f, "w"), indent=2)
print(f"  ✓ {f}")
PYEOF
}

# Claude Desktop: must use npx mcp-remote bridge for remote servers
patch_claude_desktop() {
  python3 - "$1" "$MCP_URL" "$INVITE_KEY" << 'PYEOF'
import json, sys, os
f, u, k = sys.argv[1], sys.argv[2], sys.argv[3]
def load_json_or_empty(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            raw = fh.read().strip()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
c = load_json_or_empty(f)
os.makedirs(os.path.dirname(f), exist_ok=True)
c.setdefault("mcpServers", {})
a = ["-y", "mcp-remote@latest", u]
if k: a.extend(["--header", f"Authorization: Bearer {k}"])
c["mcpServers"]["engram"] = {"command": "npx", "args": a}
json.dump(c, open(f, "w"), indent=2)
print(f"  ✓ {f}")
PYEOF
}

# OpenCode: mcp.engram = {type: "remote", url, headers?}
patch_opencode() {
  python3 - "$1" "$MCP_URL" "$INVITE_KEY" << 'PYEOF'
import json, sys, os
f, u, k = sys.argv[1], sys.argv[2], sys.argv[3]
def load_json_or_empty(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            raw = fh.read().strip()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
c = load_json_or_empty(f)
os.makedirs(os.path.dirname(f), exist_ok=True)
c.setdefault("mcp", {})
e = {"type": "remote", "url": u, "enabled": True}
if k: e["headers"] = {"Authorization": f"Bearer {k}"}
c["mcp"]["engram"] = e
json.dump(c, open(f, "w"), indent=2)
print(f"  ✓ {f}")
PYEOF
}

# Zed: context_servers.engram = {url, headers?} in settings.json
patch_zed() {
  python3 - "$1" "$MCP_URL" "$INVITE_KEY" << 'PYEOF'
import json, sys, os
f, u, k = sys.argv[1], sys.argv[2], sys.argv[3]
def load_json_or_empty(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            raw = fh.read().strip()
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
c = load_json_or_empty(f)
os.makedirs(os.path.dirname(f), exist_ok=True)
c.setdefault("context_servers", {})
e = {"url": u}
if k: e["headers"] = {"Authorization": f"Bearer {k}"}
c["context_servers"]["engram"] = e
json.dump(c, open(f, "w"), indent=2)
print(f"  ✓ {f}")
PYEOF
}

# ── Detect and patch MCP clients ──────────────────────────────────
echo ""
echo "Detecting MCP clients..."
PATCHED=0

# ── Claude Desktop ────────────────────────────────────────────────
# Uses npx mcp-remote bridge (direct url entries are silently ignored)
if [ "$OS" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Claude" ]; then
  patch_claude_desktop "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  PATCHED=$((PATCHED + 1))
fi
if [ "$OS" = "Linux" ] && [ -d "$HOME/.config/Claude" ]; then
  patch_claude_desktop "$HOME/.config/Claude/claude_desktop_config.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Claude Code ───────────────────────────────────────────────────
# Config lives in ~/.claude.json, needs type: "http"
if [ -f "$HOME/.claude.json" ] || [ -d "$HOME/.claude" ]; then
  patch_claude_code "$HOME/.claude.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Cursor ────────────────────────────────────────────────────────
if [ -f "$HOME/.cursor/mcp.json" ] || [ -d "$HOME/.cursor" ]; then
  patch_mcpservers_url "$HOME/.cursor/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# ── VS Code ──────────────────────────────────────────────────────
# Uses {servers: {type: "http", url}} in a dedicated mcp.json
if [ "$OS" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Code" ]; then
  patch_vscode "$HOME/Library/Application Support/Code/User/mcp.json"
  PATCHED=$((PATCHED + 1))
fi
if [ "$OS" = "Linux" ] && [ -d "$HOME/.config/Code" ]; then
  patch_vscode "$HOME/.config/Code/User/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Windsurf ─────────────────────────────────────────────────────
# Uses "serverUrl" not "url"
if [ -f "$HOME/.codeium/windsurf/mcp_config.json" ] || [ -d "$HOME/.codeium/windsurf" ]; then
  patch_windsurf "$HOME/.codeium/windsurf/mcp_config.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Kiro ─────────────────────────────────────────────────────────
if [ -f "$HOME/.kiro/settings/mcp.json" ] || [ -d "$HOME/.kiro" ]; then
  patch_mcpservers_url "$HOME/.kiro/settings/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Zed ──────────────────────────────────────────────────────────
# Uses "context_servers" in settings.json
if [ "$OS" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Zed" ]; then
  patch_zed "$HOME/Library/Application Support/Zed/settings.json"
  PATCHED=$((PATCHED + 1))
fi
if [ "$OS" = "Linux" ] && [ -d "$HOME/.config/zed" ]; then
  patch_zed "$HOME/.config/zed/settings.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Amazon Q Developer ───────────────────────────────────────────
if [ -d "$HOME/.aws/amazonq" ]; then
  patch_mcpservers_url "$HOME/.aws/amazonq/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Trae (ByteDance) ────────────────────────────────────────────
# VS Code fork — uses mcpServers with {url}
if [ "$OS" = "Darwin" ] && [ -d "$HOME/Library/Application Support/Trae" ]; then
  patch_mcpservers_url "$HOME/Library/Application Support/Trae/User/mcp.json"
  PATCHED=$((PATCHED + 1))
fi
if [ "$OS" = "Linux" ] && [ -d "$HOME/.config/Trae" ]; then
  patch_mcpservers_url "$HOME/.config/Trae/User/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# ── JetBrains / Junie ───────────────────────────────────────────
# User-scope MCP config: ~/.junie/mcp/mcp.json
if [ -d "$HOME/.junie" ]; then
  patch_mcpservers_url "$HOME/.junie/mcp/mcp.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Cline (VS Code extension) ───────────────────────────────────
# Stores MCP settings in ~/Documents/Cline/MCP/cline_mcp_settings.json
# and also in VS Code globalStorage
CLINE_DIR="$HOME/Documents/Cline/MCP"
if [ -d "$CLINE_DIR" ] || [ -d "$HOME/Documents/Cline" ]; then
  patch_mcpservers_url "$CLINE_DIR/cline_mcp_settings.json"
  PATCHED=$((PATCHED + 1))
fi

# ── Roo Code (VS Code extension, Cline fork) ────────────────────
# globalStorage path for Roo Code
if [ "$OS" = "Darwin" ]; then
  ROO_STORAGE="$HOME/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline"
else
  ROO_STORAGE="$HOME/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline"
fi
if [ -d "$ROO_STORAGE" ]; then
  patch_mcpservers_url "$ROO_STORAGE/settings/cline_mcp_settings.json"
  PATCHED=$((PATCHED + 1))
fi

# ── OpenCode ─────────────────────────────────────────────────────
# Uses {mcp: {name: {type: "remote", url}}} in opencode.json or ~/.config/opencode/config.json
if [ -d "$HOME/.config/opencode" ] || [ -f "$HOME/.config/opencode/config.json" ]; then
  patch_opencode "$HOME/.config/opencode/config.json"
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
