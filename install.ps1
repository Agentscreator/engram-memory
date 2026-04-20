# Engram installer for Windows PowerShell
# Usage: irm https://engram-memory.com/install.ps1 | iex
#   or:  & { $env:ENGRAM_JOIN='ek_live_...'; irm https://engram-memory.com/install.ps1 | iex }

$ErrorActionPreference = 'Stop'
$McpUrl = $env:ENGRAM_MCP_URL
if (-not $McpUrl) { $McpUrl = 'https://www.engram-memory.com/mcp' }
$InviteKey = $env:ENGRAM_JOIN

function Read-JsonOrEmpty {
    param([string]$FilePath)

    if (-not (Test-Path $FilePath)) {
        return [pscustomobject]@{}
    }

    try {
        $raw = Get-Content -LiteralPath $FilePath -Raw
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return [pscustomobject]@{}
        }
        return $raw | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{}
    }
}

function Ensure-ObjectProperty {
    param(
        [object]$Target,
        [string]$Name,
        [object]$Value
    )

    if ($null -eq $Target.PSObject.Properties[$Name]) {
        $Target | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    } else {
        $Target.$Name = $Value
    }
}

function Write-JsonFile {
    param(
        [object]$Object,
        [string]$FilePath
    )

    $directory = Split-Path -Parent $FilePath
    if ($directory -and -not (Test-Path $directory)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }

    $json = $Object | ConvertTo-Json -Depth 20
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($FilePath, $json, $encoding)
}

# ── Install engram CLI ─────────────────────────────────────────────
Write-Host "`nInstalling engram CLI..."

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "  Fetching uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    # Refresh PATH so uv is available in this session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "User") + ";" + $env:PATH
}

try {
    uv tool install "engram-team" --upgrade --quiet 2>$null
    $uvBin = "$env:USERPROFILE\.local\bin"
    if ($env:PATH -notlike "*$uvBin*") {
        $env:PATH = "$uvBin;$env:PATH"
    }
    Write-Host "  ✓ engram CLI installed"

    # Write credentials so the auto-commit hook can reach the server
    $credDir = "$env:USERPROFILE\.engram"
    if (-not (Test-Path $credDir)) { New-Item -ItemType Directory -Force -Path $credDir | Out-Null }
    $credContent = "ENGRAM_SERVER_URL=https://www.engram-memory.com`n"
    if ($InviteKey) { $credContent += "ENGRAM_INVITE_KEY=$InviteKey`n" }
    [System.IO.File]::WriteAllText("$credDir\credentials", $credContent)

    # Wire up auto-commit hooks for all detected IDEs
    try { engram install 2>$null; Write-Host "  ✓ auto-commit hooks installed" } catch {}
} catch {
    Write-Host "  ! CLI install failed — run manually: uv tool install engram-team"
}


# ── Per-IDE JSON patchers ──────────────────────────────────────────

function Patch-McpServersUrl {  # Cursor, Kiro, Trae, Amazon Q
    param([string]$f)
    $c = Read-JsonOrEmpty $f
    if ($null -eq $c.PSObject.Properties['mcpServers']) {
        $c | Add-Member -NotePropertyName 'mcpServers' -NotePropertyValue ([pscustomobject]@{})
    }
    $e = [pscustomobject]@{ url = $McpUrl }
    if ($InviteKey) {
        Ensure-ObjectProperty -Target $e -Name 'headers' -Value ([pscustomobject]@{ Authorization = "Bearer $InviteKey" })
    }
    Ensure-ObjectProperty -Target $c.mcpServers -Name 'engram' -Value $e
    Write-JsonFile $c $f
}

function Patch-Windsurf {  # serverUrl not url
    param([string]$f)
    $c = Read-JsonOrEmpty $f
    if ($null -eq $c.PSObject.Properties['mcpServers']) {
        $c | Add-Member -NotePropertyName 'mcpServers' -NotePropertyValue ([pscustomobject]@{})
    }
    $e = [pscustomobject]@{ serverUrl = $McpUrl }
    if ($InviteKey) {
        Ensure-ObjectProperty -Target $e -Name 'headers' -Value ([pscustomobject]@{ Authorization = "Bearer $InviteKey" })
    }
    Ensure-ObjectProperty -Target $c.mcpServers -Name 'engram' -Value $e
    Write-JsonFile $c $f
}

function Patch-VSCode {  # {servers: {type: "http", url}}
    param([string]$f)
    $c = Read-JsonOrEmpty $f
    if ($null -eq $c.PSObject.Properties['servers']) {
        $c | Add-Member -NotePropertyName 'servers' -NotePropertyValue ([pscustomobject]@{})
    }
    $e = [pscustomobject]@{ type = 'http'; url = $McpUrl }
    if ($InviteKey) {
        Ensure-ObjectProperty -Target $e -Name 'headers' -Value ([pscustomobject]@{ Authorization = "Bearer $InviteKey" })
    }
    Ensure-ObjectProperty -Target $c.servers -Name 'engram' -Value $e
    Write-JsonFile $c $f
}

function Patch-ClaudeCode {  # {type: "http", url} in ~/.claude.json
    param([string]$f)
    $c = Read-JsonOrEmpty $f
    if ($null -eq $c.PSObject.Properties['mcpServers']) {
        $c | Add-Member -NotePropertyName 'mcpServers' -NotePropertyValue ([pscustomobject]@{})
    }
    $e = [pscustomobject]@{ type = 'http'; url = $McpUrl }
    if ($InviteKey) {
        Ensure-ObjectProperty -Target $e -Name 'headers' -Value ([pscustomobject]@{ Authorization = "Bearer $InviteKey" })
    }
    Ensure-ObjectProperty -Target $c.mcpServers -Name 'engram' -Value $e
    Write-JsonFile $c $f
}

function Patch-ClaudeDesktop {  # npx mcp-remote bridge
    param([string]$f)
    $c = Read-JsonOrEmpty $f
    if ($null -eq $c.PSObject.Properties['mcpServers']) {
        $c | Add-Member -NotePropertyName 'mcpServers' -NotePropertyValue ([pscustomobject]@{})
    }
    $args = @('-y', 'mcp-remote@latest', $McpUrl)
    if ($InviteKey) {
        $args += @('--header', "Authorization: Bearer $InviteKey")
    }
    $e = [pscustomobject]@{ command = 'npx'; args = $args }
    Ensure-ObjectProperty -Target $c.mcpServers -Name 'engram' -Value $e
    Write-JsonFile $c $f
}

function Patch-OpenCode {  # {mcp: {engram: {type: "remote", url}}}
    param([string]$f)
    $c = Read-JsonOrEmpty $f
    if ($null -eq $c.PSObject.Properties['mcp']) {
        $c | Add-Member -NotePropertyName 'mcp' -NotePropertyValue ([pscustomobject]@{})
    }
    $e = [pscustomobject]@{ type = 'remote'; url = $McpUrl; enabled = $true }
    if ($InviteKey) {
        Ensure-ObjectProperty -Target $e -Name 'headers' -Value ([pscustomobject]@{ Authorization = "Bearer $InviteKey" })
    }
    Ensure-ObjectProperty -Target $c.mcp -Name 'engram' -Value $e
    Write-JsonFile $c $f
}

# ── Detect and patch MCP clients ──────────────────────────────────
Write-Host "`nDetecting MCP clients..."
$patched = 0

# Claude Desktop
if (Test-Path "$env:APPDATA\Claude") {
    Patch-ClaudeDesktop "$env:APPDATA\Claude\claude_desktop_config.json"
    $patched++
}

# Claude Code (~/.claude.json)
if ((Test-Path "$env:USERPROFILE\.claude.json") -or (Test-Path "$env:USERPROFILE\.claude")) {
    Patch-ClaudeCode "$env:USERPROFILE\.claude.json"
    $patched++
}

# Cursor
if (Test-Path "$env:USERPROFILE\.cursor") {
    Patch-McpServersUrl "$env:USERPROFILE\.cursor\mcp.json"
    $patched++
}

# VS Code
if (Test-Path "$env:APPDATA\Code") {
    Patch-VSCode "$env:APPDATA\Code\User\mcp.json"
    $patched++
}

# Windsurf
if (Test-Path "$env:USERPROFILE\.codeium\windsurf") {
    Patch-Windsurf "$env:USERPROFILE\.codeium\windsurf\mcp_config.json"
    $patched++
}

# Kiro
if (Test-Path "$env:USERPROFILE\.kiro") {
    Patch-McpServersUrl "$env:USERPROFILE\.kiro\settings\mcp.json"
    $patched++
}

# Amazon Q Developer
if (Test-Path "$env:USERPROFILE\.aws\amazonq") {
    Patch-McpServersUrl "$env:USERPROFILE\.aws\amazonq\mcp.json"
    $patched++
}

# Trae (ByteDance)
if (Test-Path "$env:APPDATA\Trae") {
    Patch-McpServersUrl "$env:APPDATA\Trae\User\mcp.json"
    $patched++
}

# JetBrains / Junie
if (Test-Path "$env:USERPROFILE\.junie") {
    Patch-McpServersUrl "$env:USERPROFILE\.junie\mcp\mcp.json"
    $patched++
}

# Cline (VS Code extension)
$clineMcp = "$env:USERPROFILE\Documents\Cline\MCP\cline_mcp_settings.json"
if (Test-Path "$env:USERPROFILE\Documents\Cline") {
    Patch-McpServersUrl $clineMcp
    $patched++
}

# Roo Code (VS Code extension)
$rooStorage = "$env:APPDATA\Code\User\globalStorage\rooveterinaryinc.roo-cline"
if (Test-Path $rooStorage) {
    Patch-McpServersUrl "$rooStorage\settings\cline_mcp_settings.json"
    $patched++
}

# OpenCode
if (Test-Path "$env:USERPROFILE\.config\opencode") {
    Patch-OpenCode "$env:USERPROFILE\.config\opencode\config.json"
    $patched++
}

# ── Install Claude Code skill (global, all sessions) ───────────────
$SkillDir = "$env:USERPROFILE\.claude\skills"
$SkillFile = "$SkillDir\set-up-engram-for-my-team.md"
if (-not (Test-Path $SkillDir)) { New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null }
@'
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
Then merge into ~/.claude.json.

### Self-hosted + Project-level

Same as above but write to .mcp.json.

## Step 4 — Next steps

Tell the user:
1. Which file was written and what was added
2. The MCP URL is https://www.engram-memory.com/mcp
3. To restart Claude Code (or run /mcp) for the change to take effect
4. Once restarted: call engram_status() — it will guide through engram_init (new workspace) or engram_join (join with invite key)
'@ | Set-Content -LiteralPath $SkillFile -Encoding UTF8
Write-Host "  ✓ $SkillFile"

# ── Result ─────────────────────────────────────────────────────────
Write-Host ''
if ($patched -eq 0) {
    Write-Host 'No MCP clients detected. Manually add to your IDE''s MCP config:'
    Write-Host ''
    Write-Host "  Remote MCP URL: $McpUrl"
    if ($InviteKey) { Write-Host "  Header: Authorization: Bearer $InviteKey" }
    Write-Host ''
    Write-Host 'Then restart your IDE.'
} else {
    Write-Host 'Done!'
    Write-Host ''
    Write-Host '  Restart your terminal, then run:'
    Write-Host ''
    Write-Host '    engram                 - get started'
    Write-Host '    engram conflicts       - review memory conflicts'
    Write-Host '    engram search <term>   - query workspace memory'
    Write-Host ''
    Write-Host '  Or restart your IDE and ask your agent:'
    if (-not $InviteKey) {
        Write-Host ''
        Write-Host '  "Set up Engram for my team"         - create a new workspace'
        Write-Host '  "Join Engram with key ek_live_..."  - join a teammate''s workspace'
    } else {
        Write-Host ''
        Write-Host '  "Set up Engram"  - your agent will connect to your workspace'
    }
}
Write-Host ''
