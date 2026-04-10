# Troubleshooting

This guide helps recover from common Engram setup and installation problems.

## 1. IDE did not pick up MCP config after install

### Symptom
The install command completed, but Engram tools do not appear in the agent or IDE.

### Likely cause
The IDE was open during installation and did not reload the new MCP configuration.

### Fix
1. Fully close the IDE.
2. Reopen the IDE.
3. Start a fresh session.
4. Try running `engram_status` again.

---

## 2. Wrong MCP config file was updated

### Symptom
Install appears to succeed, but the IDE still cannot see Engram.

### Likely cause
The installer wrote to the wrong config location, or the user checked the wrong config file.

### Fix
1. Confirm which IDE you are using.
2. Check that IDE’s MCP configuration file.
3. Verify that the Engram MCP entry exists there.
4. Restart the IDE after confirming the config.

---

## 3. `workspace.json` is missing or corrupted

### Symptom
Joining or loading a workspace fails, or Engram reports that the workspace is invalid.

### Likely cause
The workspace file is incomplete, manually edited incorrectly, or corrupted.

### Fix
1. Remove the broken `workspace.json` if it is clearly invalid.
2. Re-run the workspace setup or join flow.
3. Avoid manually editing the file unless the format is documented.
4. Retry `engram_status` after setup completes.

---

## 4. NLI model failed to download on first run

### Symptom
First-time setup hangs, errors, or fails during model download.

### Likely cause
A network interruption, blocked download, or incomplete first-run setup.

### Fix
1. Check your internet connection.
2. Retry the setup command.
3. Wait for the first-run download to finish completely.
4. If the problem continues, capture the terminal error and include it in an issue.

---

## 5. `engram_status` shows unconfigured after join

### Symptom
Workspace join appears to complete, but `engram_status` still shows the system as unconfigured.

### Likely cause
Setup did not finish cleanly, the workspace file was not written correctly, or the IDE has stale config.

### Fix
1. Restart the IDE.
2. Re-run the join or setup flow.
3. Confirm that `workspace.json` exists and is valid.
4. Run `engram_status` again in a fresh session.

---

## 6. Claude Desktop setup fails because Node.js or `mcp-remote` is missing

### Symptom
Claude Desktop integration fails or cannot start the MCP connection.

### Likely cause
Node.js is not installed, or the required MCP bridge command is unavailable.

### Fix
1. Install Node.js.
2. Confirm Node is available by running `node -v`.
3. Re-run the Engram setup flow.
4. Restart Claude Desktop and try again.

---

## 7. Windows install fails because PATH is incorrect

### Symptom
Commands are not recognized, or install scripts fail on Windows.

### Likely cause
Required tools are installed but not available in the system PATH.

### Fix
1. Close the terminal.
2. Reopen the terminal after installation.
3. Verify the required commands are available.
4. If needed, update PATH and retry the install.

---

## 8. IDE was not restarted after config changes

### Symptom
The config file looks correct, but Engram still does not show up.

### Likely cause
The IDE cached old configuration and did not reload the updated MCP settings.

### Fix
1. Fully quit the IDE.
2. Reopen it.
3. Start a new session instead of reusing an old one.
4. Check whether Engram tools now appear.

---

## 9. MCP config file contains invalid JSON

### Symptom
The IDE rejects the config, ignores Engram, or fails silently.

### Likely cause
A missing comma, quote, bracket, or other JSON formatting issue.

### Fix
1. Open the MCP config file.
2. Check for JSON syntax errors.
3. Fix any missing commas, quotes, or braces.
4. Save the file and restart the IDE.

---

## 10. Backend URL is incorrect or blocked

### Symptom
Engram appears configured, but requests fail or cannot connect.

### Likely cause
The configured backend endpoint is wrong, unavailable, or blocked by network settings.

### Fix
1. Verify the configured backend URL.
2. Confirm it matches the expected setup value.
3. Check whether your network or firewall is blocking access.
4. Retry after correcting the endpoint.

---

## 12. Command not recognized

### Symptom
Running `engram` shows "Error: No such command 'xyz'"

### Likely cause
Using an old Engram version that doesn't include the command.

### Fix
1. Update Engram: `pip install --upgrade engram`
2. Or reinstall: `curl -fsSL https://engram-us.com/install | sh`
3. Check available commands: `engram --help`

---

## General recovery steps

If setup fails and the exact cause is unclear:

1. Close the IDE completely.
2. Reopen the terminal.
3. Retry the setup flow from the beginning.
4. Check `engram_status`.
5. Capture the exact error output before opening an issue.

When reporting a problem, include:
- your operating system
- your IDE
- the exact command you ran
- the full error message
- whether this was a first-time install or a reconfiguration
