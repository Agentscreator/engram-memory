# Time-Limited Invite Links

Engram supports time-limited invite keys that automatically expire after a specified period.

## How It Works

Invite keys can be created with an expiration period:

```python
# Create invite key that expires in 7 days (default is 90 days)
result = await engram_init(
    invite_expires_days=7,
    invite_uses=5
)
```

## Using Time-Limited Keys

### Generate a time-limited invite key

```bash
# Via MCP tool
await engram_init(invite_expires_days=7)

# Or via CLI (when setting up workspace)
engram setup --expires-in-days 7
```

### Check if an invite key is still valid

```bash
engram config show
```

The dashboard also shows invite key expiration status at `/dashboard/settings`.

## CLI Support for Expiring Invites

```bash
# Generate invite key that expires in 30 days
engram setup --invite-expires-days 30

# Generate one-time use invite link
engram setup --invite-uses 1
```

## Invite Key Expiration Behavior

| Event | What Happens |
|-------|--------------|
| Key expires | Key becomes invalid, users see "expired" error |
| All uses consumed | Key becomes invalid, users see "used up" error |
| Key reset | All existing keys revoked, new key generated |

## Best Practices

1. **Short-term invites (7 days):** For onboarding new team members
2. **One-time use:** For sensitive access sharing
3. **30-day expires:** Default for ongoing team access
4. **90-day expires:** For long-term contractors

## API Reference

- `engram_init(invite_expires_days: int = 90)` — Set expiration
- `engram_join(invite_key)` — Join with expiring key
- `engram_reset_invite_key()` — Revoke all expiring keys