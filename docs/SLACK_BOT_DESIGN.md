# Slack Bot Design

> **Issue #40** — Query and commit from Slack chat.

## Solution

Two slash commands:

### `/engram ask <question>`
Query workspace, returns top 5 facts as formatted Slack message.

### `/engram learn <fact>`
Commit a human-written fact to the workspace.

## Architecture

```
Slack → Slack App (Python/Flask) → Engram REST API
```

## Implementation

1. **Phase 1**: Basic slash commands using existing REST API
2. **Phase 2**: Rich UI with interactive buttons
3. **Phase 3**: Bot mode with @mention support

---

*Design by ismaeldouglasdev — 2026-04-12*