#!/bin/sh
# Engram installer — adds Engram to your MCP config
# Usage: curl -fsSL https://engram-memory.com/install | sh
#   or:  curl -fsSL https://engram-memory.com/install | sh -s -- --join ek_live_...

set -e

MCP_URL="${ENGRAM_MCP_URL:-https://www.engram-memory.com/mcp}"
INVITE_KEY="${ENGRAM_JOIN:-}"

# Parse --join flag (overrides ENGRAM_JOIN env var if both are set)
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

# ── Install engram CLI ─────────────────────────────────────────────
echo ""
echo "Installing engram CLI..."

if ! command -v uv >/dev/null 2>&1; then
  echo "  Fetching uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env" 2>/dev/null || true
fi

if uv tool install "engram-team" --upgrade --quiet 2>/dev/null; then
  export PATH="$HOME/.local/bin:$PATH"
  echo "  ✓ engram CLI installed"

  # Write credentials so the auto-commit hook can reach the server
  mkdir -p "$HOME/.engram"
  printf "ENGRAM_SERVER_URL=https://www.engram-memory.com\n" > "$HOME/.engram/credentials"
  if [ -n "$INVITE_KEY" ]; then
    printf "ENGRAM_INVITE_KEY=%s\n" "$INVITE_KEY" >> "$HOME/.engram/credentials"
  fi
  chmod 600 "$HOME/.engram/credentials"

  # Wire up auto-commit hooks for all detected IDEs
  engram install 2>/dev/null && echo "  ✓ auto-commit hooks installed" || true
else
  echo "  ! CLI install failed — run manually: uv tool install engram-team"
fi

# ── Require Python 3 ───────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required but not found. Please install it first."
  exit 1
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

# ── Install Claude Code skill (global, all sessions) ───────────────
SKILL_DIR="$HOME/.claude/skills"
SKILL_FILE="$SKILL_DIR/set-up-engram-for-my-team.md"
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
mkdir -p "$SKILL_DIR"
cat > "$SKILL_FILE" << 'SKILLEOF'
# Set Up Engram for My Team

Guide the user through configuring the Engram MCP server in their IDE.

## CRITICAL — Correct MCP URL

The ONLY correct Engram MCP endpoint is:

    https://www.engram-memory.com/mcp

DO NOT invent subdomains like mcp.engram-memory.com or mcp.engram.app — they do not exist.
DO NOT omit the www prefix. Always use exactly:

    https://www.engram-memory.com/mcp

## Step 1 — Check existing config and auto-fix wrong URLs

Read ~/.claude.json and .mcp.json (if they exist). If either contains an "engram"
entry under mcpServers with a WRONG url (anything other than https://www.engram-memory.com/mcp,
e.g. mcp.engram.app or mcp.engram-memory.com), fix it to https://www.engram-memory.com/mcp and tell the user you
corrected it.

If Engram is already correctly configured, tell the user and skip to Step 4.

## Step 2 — Ask two questions in a single AskUserQuestion call

**Question 1 — header: "Engram type"**
question: "What Engram implementation do you want to use?"
options:
1. label: "Engram hosted server (Recommended)" — description: "Use the managed Engram MCP server at engram-memory.com — no installation needed, easiest to get started"
2. label: "Self-hosted / custom" — description: "You have your own Engram server URL or a local binary you want to connect to"
3. label: "Walk me through the options and tradeoffs" — description: "Explain the differences before I decide"
4. label: "Chat about this" — description: "I have a question first"

**Question 2 — header: "Scope"**
question: "Where should Engram be configured?"
options:
1. label: "User-level (~/.claude.json) (Recommended)" — description: "Available across all your Claude Code projects, not tied to any single repo"
2. label: "Project-level (.mcp.json)" — description: "Checked into this repo — all agents working in this directory share the config"
3. label: "Chat about this" — description: "I have a question first"

If the user picks "Walk me through the options" or "Chat about this" on either question, answer their question then re-ask before proceeding.

## Step 3 — Write config

IMPORTANT: The url MUST be exactly https://www.engram-memory.com/mcp — no other domain.

### Hosted + User-level (~/.claude.json)

Read ~/.claude.json if it exists, then merge:
```json
{
  "mcpServers": {
    "engram": {
      "type": "http",
      "url": "https://www.engram-memory.com/mcp"
    }
  }
}
```
Write merged result back to ~/.claude.json.

### Hosted + Project-level (.mcp.json)

Read .mcp.json in the project root if it exists, then merge:
```json
{
  "mcpServers": {
    "engram": {
      "type": "http",
      "url": "https://www.engram-memory.com/mcp"
    }
  }
}
```
Write merged result back to .mcp.json.

### Self-hosted + User-level

Ask: "What is your Engram server URL?"
Then merge into ~/.claude.json:
```json
{
  "mcpServers": {
    "engram": {
      "type": "http",
      "url": "<provided URL>"
    }
  }
}
```

### Self-hosted + Project-level

Same as above but write to .mcp.json.

## Step 4 — Next steps

Tell the user:
1. Which file was written and what was added
2. The MCP URL is https://www.engram-memory.com/mcp
3. To restart Claude Code (or run /mcp) for the change to take effect
4. Once restarted: the Engram MCP tools will be available. Call engram_status() — it will guide them through engram_init (create a new team workspace) or engram_join (join a teammate's workspace with an invite key)
SKILLEOF
echo "  ✓ ~/.claude/skills/set-up-engram-for-my-team.md"

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
  echo "Done!"
  echo ""
  echo "  Restart your terminal, then run:"
  echo ""
  echo "    engram                — get started"
  echo "    engram conflicts      — review memory conflicts"
  echo "    engram search <term>  — query workspace memory"
  echo ""
  echo "  Or restart your IDE and ask your agent:"
  if [ -z "$INVITE_KEY" ]; then
    echo ""
    echo "    \"Set up Engram for my team\"         — create a new workspace"
    echo "    \"Join Engram with key ek_live_...\"  — join a teammate's workspace"
  else
    echo ""
    echo "    \"Set up Engram\"  — your agent will connect to your workspace"
  fi
fi
echo ""
