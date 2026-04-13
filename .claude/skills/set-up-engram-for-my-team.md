# Set Up Engram for My Team

Guide the user through configuring the Engram MCP server in their IDE.

## CRITICAL — Correct MCP URL

The ONLY correct Engram MCP endpoint is:

    https://www.engram-memory.com/mcp

DO NOT invent subdomains like mcp.engram-memory.com or mcp.engram.app — they do not exist.
DO NOT omit the www prefix. Always use exactly:

    https://www.engram-memory.com/mcp

## Step 1 — Check existing config and auto-fix wrong URLs

Read `~/.claude.json` and `.mcp.json` (if they exist). If either contains an `"engram"`
entry under `mcpServers` with a WRONG url (anything other than `https://www.engram-memory.com/mcp`,
e.g. `mcp.engram.app` or `mcp.engram-memory.com`), fix it to `https://www.engram-memory.com/mcp` and tell the user you
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

IMPORTANT: The url MUST be exactly `https://www.engram-memory.com/mcp` — no other domain.

### Hosted + User-level (~/.claude.json)

Read `~/.claude.json` if it exists, then merge:
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
Write merged result back to `~/.claude.json`.

### Hosted + Project-level (.mcp.json)

Read `.mcp.json` in the project root if it exists, then merge:
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
Write merged result back to `.mcp.json`.

### Self-hosted + User-level

Ask: "What is your Engram server URL?"
Then merge into `~/.claude.json`:
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

Same as above but write to `.mcp.json`.

## Step 4 — Next steps

Tell the user:
1. Which file was written and what was added
2. The MCP URL is `https://www.engram-memory.com/mcp`
3. To restart Claude Code (or run `/mcp`) for the change to take effect
4. Once restarted: the Engram MCP tools will be available. Call `engram_status()` — it will guide them through `engram_init` (create a new team workspace) or `engram_join` (join a teammate's workspace with an invite key)
