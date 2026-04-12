@echo off
REM Engram installer for Windows CMD
REM Usage: curl -fsSL https://engram-memory.com/install.cmd -o install.cmd && install.cmd && del install.cmd

setlocal enabledelayedexpansion

if defined ENGRAM_MCP_URL (
    set "MCP_URL=%ENGRAM_MCP_URL%"
) else (
    set "MCP_URL=https://mcp.engram.app/mcp"
)
set "INVITE_KEY="

REM ── Require Python 3 ─────────────────────────────────────────────
where python3 >nul 2>&1
if %errorlevel% equ 0 (
    set "PY=python3"
) else (
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY=python"
    ) else (
        echo Python 3 is required but not found. Please install it first.
        exit /b 1
    )
)

REM ── Ask for invite key ───────────────────────────────────────────
echo.
set /p "HAS_KEY=Do you have an invite key from a teammate? (y/n): "
if /i "%HAS_KEY%"=="y" (
    set /p "INVITE_KEY=Paste your invite key: "
)

REM ── Write shared Python patcher ──────────────────────────────────
set "PATCHER=%TEMP%\engram_patch.py"
(
echo import json, sys, os
echo.
echo def load^(path^):
echo     if not os.path.exists^(path^): return {}
echo     try:
echo         raw = open^(path^).read^(^).strip^(^)
echo         return json.loads^(raw^) if raw else {}
echo     except json.JSONDecodeError: return {}
echo.
echo fmt, f, u, k = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
echo c = load^(f^)
echo d = os.path.dirname^(f^)
echo if d: os.makedirs^(d, exist_ok=True^)
echo if fmt == 'url':
echo     c.setdefault^('mcpServers', {}^)
echo     e = {'url': u}
echo     if k: e['headers'] = {'Authorization': 'Bearer ' + k}
echo     c['mcpServers']['engram'] = e
echo elif fmt == 'windsurf':
echo     c.setdefault^('mcpServers', {}^)
echo     e = {'serverUrl': u}
echo     if k: e['headers'] = {'Authorization': 'Bearer ' + k}
echo     c['mcpServers']['engram'] = e
echo elif fmt == 'vscode':
echo     c.setdefault^('servers', {}^)
echo     e = {'type': 'http', 'url': u}
echo     if k: e['headers'] = {'Authorization': 'Bearer ' + k}
echo     c['servers']['engram'] = e
echo elif fmt == 'claude-code':
echo     c.setdefault^('mcpServers', {}^)
echo     e = {'type': 'http', 'url': u}
echo     if k: e['headers'] = {'Authorization': 'Bearer ' + k}
echo     c['mcpServers']['engram'] = e
echo elif fmt == 'claude-desktop':
echo     c.setdefault^('mcpServers', {}^)
echo     a = ['-y', 'mcp-remote@latest', u]
echo     if k: a.extend^(['--header', 'Authorization: Bearer ' + k]^)
echo     c['mcpServers']['engram'] = {'command': 'npx', 'args': a}
echo elif fmt == 'opencode':
echo     c.setdefault^('mcp', {}^)
echo     e = {'type': 'remote', 'url': u, 'enabled': True}
echo     if k: e['headers'] = {'Authorization': 'Bearer ' + k}
echo     c['mcp']['engram'] = e
echo json.dump^(c, open^(f, 'w'^), indent=2^)
echo print^('  + ' + f^)
) > "%PATCHER%"

REM ── Detect and patch MCP clients ────────────────────────────────
echo.
echo Detecting MCP clients...
set "PATCHED=0"

REM Claude Desktop — npx mcp-remote bridge
if exist "%APPDATA%\Claude" (
    call :patch claude-desktop "%APPDATA%\Claude\claude_desktop_config.json"
)

REM Claude Code — {type: "http", url} in ~/.claude.json
set "CC_FOUND=0"
if exist "%USERPROFILE%\.claude"      set "CC_FOUND=1"
if exist "%USERPROFILE%\.claude.json" set "CC_FOUND=1"
if "%CC_FOUND%"=="1" (
    call :patch claude-code "%USERPROFILE%\.claude.json"
)

REM Cursor
if exist "%USERPROFILE%\.cursor" (
    call :patch url "%USERPROFILE%\.cursor\mcp.json"
)

REM VS Code — {servers: {type: "http", url}}
if exist "%APPDATA%\Code" (
    call :patch vscode "%APPDATA%\Code\User\mcp.json"
)

REM Windsurf — serverUrl
if exist "%USERPROFILE%\.codeium\windsurf" (
    call :patch windsurf "%USERPROFILE%\.codeium\windsurf\mcp_config.json"
)

REM Kiro
if exist "%USERPROFILE%\.kiro" (
    call :patch url "%USERPROFILE%\.kiro\settings\mcp.json"
)

REM Amazon Q Developer
if exist "%USERPROFILE%\.aws\amazonq" (
    call :patch url "%USERPROFILE%\.aws\amazonq\mcp.json"
)

REM Trae (ByteDance)
if exist "%APPDATA%\Trae" (
    call :patch url "%APPDATA%\Trae\User\mcp.json"
)

REM JetBrains / Junie
if exist "%USERPROFILE%\.junie" (
    call :patch url "%USERPROFILE%\.junie\mcp\mcp.json"
)

REM Cline (VS Code extension)
if exist "%USERPROFILE%\Documents\Cline" (
    call :patch url "%USERPROFILE%\Documents\Cline\MCP\cline_mcp_settings.json"
)

REM Roo Code (VS Code extension, Cline fork)
if exist "%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline" (
    call :patch url "%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\cline_mcp_settings.json"
)

REM OpenCode — {mcp: {type: "remote", url}}
if exist "%USERPROFILE%\.config\opencode" (
    call :patch opencode "%USERPROFILE%\.config\opencode\config.json"
)

del "%PATCHER%" >nul 2>&1

REM ── Result ───────────────────────────────────────────────────────
echo.
if %PATCHED% equ 0 (
    echo No MCP clients detected. Manually add to your IDE's MCP config:
    echo.
    echo   Remote MCP URL: %MCP_URL%
    if not "%INVITE_KEY%"=="" echo   Header: Authorization: Bearer %INVITE_KEY%
    echo.
    echo Then restart your IDE.
) else (
    echo Done! Restart your IDE, then ask your agent:
    echo.
    if "%INVITE_KEY%"=="" (
        echo   "Set up Engram for my team"    - to create a new workspace
        echo   "Join Engram with key ek_live_..."  - to join a teammate's workspace
    ) else (
        echo   "Set up Engram"  - your agent will connect to your workspace
    )
)
echo.
goto :eof

:patch
%PY% "%PATCHER%" %~1 "%~2" "%MCP_URL%" "%INVITE_KEY%"
set /a PATCHED+=1
goto :eof
