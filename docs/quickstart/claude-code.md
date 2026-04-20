# Claude Code

## If you're setting up Engram for your team

Run the installer once:

```bash
curl -fsSL https://engram-memory.com/install | sh
```

Restart Claude Code, then ask your agent:

```
"Set up Engram for my team"
```

Your agent creates a workspace, writes `.engram.env` to your repo, and
starts committing. Share the invite link from the dashboard with your team.

## If you're joining a teammate's workspace

You don't need to install anything. Click the invite link your teammate
shared, sign in at [engram-memory.com](https://engram-memory.com), and
accept the workspace invite.

When you open the codebase, Claude Code reads `.engram.env` from the repo
and connects automatically. Your messages will be recorded in shared
memory — this is what you agreed to when you accepted the invite.

## Verification

```bash
engram verify
```

Or ask your agent: `"Call engram_status and tell me what it returns."`

Expected: `{"status": "ready", "mode": "team", "engram_id": "ENG-XXXXXX"}`

## Troubleshooting

- Check config: `cat ~/.claude/settings.json`
- Restart Claude Code after any config changes
- Full guide: [docs/TROUBLESHOOTING.md](../TROUBLESHOOTING.md)
