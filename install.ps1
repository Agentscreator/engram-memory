# Engram installer for Windows PowerShell
# Usage: irm https://engram-memory.com/install.ps1 | iex
#   or:  & { $env:ENGRAM_JOIN='ek_live_...'; irm https://engram-memory.com/install.ps1 | iex }

$ErrorActionPreference = 'Stop'
$McpUrl = $env:ENGRAM_MCP_URL
if (-not $McpUrl) { $McpUrl = 'https://mcp.engram.app/mcp' }
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

# ── Ask for invite key if not provided ─────────────────────────────
if (-not $InviteKey) {
    $hasKey = Read-Host "`nDo you have an invite key from a teammate? (y/n)"
    if ($hasKey -eq 'y' -or $hasKey -eq 'Y') {
        $InviteKey = Read-Host 'Paste your invite key'
    }
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
    Write-Host 'Done! Restart your IDE, then ask your agent:'
    if (-not $InviteKey) {
        Write-Host ''
        Write-Host '  "Set up Engram for my team"    - to create a new workspace'
        Write-Host '  "Join Engram with key ek_live_..."  - to join a teammate''s workspace'
    } else {
        Write-Host ''
        Write-Host '  "Set up Engram"  - your agent will connect to your workspace'
    }
}
Write-Host ''
