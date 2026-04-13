# Privacy & Zero-Knowledge Architecture

This document explains how Engram enforces "we don't read your facts" — the technical guarantees that make this claim verifiable, not just marketing.

## Executive Summary

Engram is designed as a **zero-knowledge memory layer**. The Engram server never sees the plaintext content of your facts. All encryption and decryption happens client-side, and the server operates on encrypted data it cannot decrypt.

## What Engram Can and Cannot Access

### What the Server CAN Access

| Capability | What It Means |
|------------|---------------|
| Database connection | Establishes connections to your PostgreSQL database |
| Schema operations | Creates/reads/updates tables in the `engram` schema |
| Fact metadata | Sees `scope`, `confidence`, `fact_type`, `committed_at`, `agent_id` — but NOT content |
| Conflict detection | Runs similarity matching on embeddings — never sees what they mean |
| Agent statistics | Aggregates commit counts, timestamps — no content inspection |

### What the Server CANNOT Access

| Capability | Why It's Impossible |
|------------|---------------------|
| Fact content | Content is encrypted client-side with your workspace key before being sent |
| Embeddings | Embeddings are generated client-side using a key derived from your workspace |
| Invite key payload | Database URL is encrypted inside the invite key — server only passes it through |
| Engineer identities | If `anonymous_mode=true`, engineer names are stripped before reaching server |

## Encryption Architecture

### Client-Side Encryption Flow

```
User's IDE/Agent
       │
       ▼
┌─────────────────────────┐
│ 1. Generate embedding   │
│    (using workspace key)│
└─────────────────────────┘
       │
       ▼
┌─────────────────────────┐
│ 2. Encrypt content      │
│    (AES-256-GCM)        │
└─────────────────────────┘
       │
       ▼
┌─────────────────────────┐
│ 3. Send to PostgreSQL   │
│    (encrypted blob)     │
└─────────────────────────┘
       │
       ▼
   PostgreSQL
   (sees only ciphertext)
```

### Key Hierarchy

```
┌─────────────────────────────────────────────┐
│           Workspace Master Key              │
│    (derived from invite key / local secret) │
└──────────────────┬──────────────────────────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   Content    Embedding   Metadata
   Key        Key         (unencrypted)
```

- **Content Key**: Encrypts the fact content field
- **Embedding Key**: Generates semantic embeddings (server never sees this key)
- **Metadata**: Remains unencrypted for querying/filtering (scope, confidence, timestamps)

## Database Visibility

### What PostgreSQL Sees

```sql
-- This is what the database actually stores:

SELECT id, scope, confidence, fact_type, committed_at, agent_id, content_encrypted, embedding_encrypted
FROM engram.facts;

-- Result:
-- id: 'fact_abc123'
-- scope: 'auth'                    ← visible
-- confidence: 0.95                 ← visible  
-- fact_type: 'observation'         ← visible
-- committed_at: '2026-04-10...'   ← visible
-- agent_id: 'claude-code'         ← visible
-- content_encrypted: 'AESgcm:AQ..'← encrypted blob (unreadable)
-- embedding_encrypted: 'AESgcm:..'← encrypted blob (unreadable)
```

The database administrator cannot read `content_encrypted` or `embedding_encrypted` without the workspace key.

### What PostgreSQL Cannot See

- The actual text content of any fact
- The semantic meaning (embeddings are encrypted)
- Which engineer made a commit (if anonymous_mode=true)
- The database URL in invite keys (encrypted payload)

## Invite Key Security

Invite keys are **encrypted payloads**, not just tokens:

```python
# What the invite key actually contains (encrypted):
{
    "db_url": "postgres://user:password@host:5432/db",  # encrypted
    "engram_id": "ENG-XXXXXX",
    "schema": "engram",
    "key_generation": 1,
    "expires_at": 1715404800,
    "uses_remaining": 10
}
```

When a teammate joins with an invite key:
1. The key is decrypted client-side using the workspace master key
2. Database credentials are extracted but never exposed to the server
3. The server only receives the connection string it needs to connect

## Threat Model

### What We're Protecting Against

| Threat | Protection |
|--------|------------|
| Database admin reading facts | Content encrypted client-side |
| Server logs leaking content | Server never receives plaintext |
| Invite key interception | Key is encrypted, not just signed |
| Team member overreach | Anonymous mode strips engineer IDs |
| Backup exposure | Backups contain only encrypted blobs |

### What We Don't Protect Against

| Scenario | Reason |
|----------|--------|
| User pasting secrets in fact content | We scan for secrets but user must not paste them |
| Compromised workspace.json | If attacker gets your workspace file, they can decrypt your facts |
| Malicious team member | Trust within team is assumed — we provide audit trails, not isolation |
| Keylogger on user's machine | If your machine is compromised, all bets are off |

## Verification

### How to Verify Zero-Knowledge

1. **Inspect database directly**:
   ```sql
   -- You'll see only encrypted blobs, never plaintext
   SELECT content_encrypted FROM engram.facts LIMIT 1;
   -- Result: 'AESgcm:AQAAAA...' (unreadable without key)
   ```

2. **Check server logs**:
   ```bash
   # Search for fact content in logs — it should never appear
   grep "content" /var/log/engram.log
   # Should return nothing related to fact content
   ```

3. **Audit network traffic**:
   ```bash
   # Verify server receives encrypted blobs, not plaintext
   tcpdump -i any -A | grep "fact_content"
   # Should only see base64-encoded ciphertext
   ```

## Comparison with Alternatives

| Feature | Engram | Traditional MCP | Vector DB + Encryption |
|---------|--------|-----------------|------------------------|
| Server sees plaintext | ❌ Never | ✅ Yes | ❌ No |
| Embeddings encrypted | ✅ Yes | ✅ Yes | ❌ Optional |
| Invite key security | ✅ Encrypted payload | ❌ Plaintext URL | ❌ URL in config |
| Anonymous mode | ✅ Yes | ❌ No | ❌ No |
| Audit trails | ✅ Per-fact metadata | ✅ Basic | ✅ Basic |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        User's Machine                           │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────────┐   │
│  │ IDE/Agent   │───▶│ Engram CLI  │───▶│ Encryption Layer │   │
│  │             │    │             │    │ (client-side)    │   │
│  └─────────────┘    └─────────────┘    └────────┬─────────┘   │
└──────────────────────────────────────────────────┼────────────┘
                                                   │
                                          Encrypted payload
                                                   │
                           ┌───────────────────────┴───────────────┐
                           ▼                                       ▼
                    ┌──────────────┐                     ┌──────────────┐
                    │ PostgreSQL   │                     │ Engram MCP   │
                    │ (encrypted  │                     │ Server       │
                    │  data only) │                     │ (metadata,   │
                    └──────────────┘                     │ stats only) │
                                                         └──────────────┘
```

## Implementation Notes

### Encryption Libraries

- **Algorithm**: AES-256-GCM (authenticated encryption)
- **Key Derivation**: PBKDF2 with SHA-256, 100,000 iterations
- **Library**: `cryptography` (Python) or equivalent in your language

### Storage Schema

```sql
-- facts table stores encrypted content
CREATE TABLE engram.facts (
    id UUID PRIMARY KEY,
    content_encrypted BYTEA NOT NULL,  -- encrypted client-side
    embedding_encrypted BYTEA,         -- encrypted client-side  
    scope TEXT NOT NULL,                -- unencrypted (for indexing)
    confidence FLOAT,                   -- unencrypted
    fact_type TEXT,                    -- unencrypted
    committed_at TIMESTAMPTZ,           -- unencrypted
    agent_id TEXT,                     -- unencrypted
    ...
);
```

## GDPR Subject Erasure

`anonymous_mode` prevents future attribution but does **not** erase historical
data already stored.  For EU customers, or any workspace subject to GDPR /
right-to-erasure requirements, Engram provides a dedicated erasure pipeline.

### When to use subject erasure

| Situation | Recommendation |
|-----------|---------------|
| Team member leaves, future commits should be anonymous | `anonymous_mode = true` is sufficient |
| Legal right-to-erasure request received | Use `engram_gdpr_erase` / `engram gdpr erase` |
| Data breach: agent content must be destroyed | Hard erase + delete backups |

### Soft erase

Redacts the `engineer` (free-text name) and `provenance` fields on every fact
version committed by the agent.  Conflict `explanation` and suggestion strings
are also scrubbed to prevent indirect leakage.  Fact content is preserved, so
the team's knowledge base remains coherent.  The agent's entry in the registry
is also anonymised.

```
Before: engineer = "alice@example.com"  content = "Cache TTL must be 300s"
After:  engineer = "[redacted]"          content = "Cache TTL must be 300s"  ← unchanged
```

### Hard erase

Everything in soft mode, plus:

- Fact `content` is replaced with a per-row placeholder (`[gdpr:erased:<id>]`)
  that cannot be retrieved by content or semantic search.
- `keywords`, `entities`, and `embedding` are cleared.
- The validity window (`valid_until`) is closed on all still-current facts,
  effectively retiring them from the live knowledge base.
- Every open conflict that references an erased fact is dismissed with
  `resolution_type = 'gdpr_erasure'`.  Resolved conflicts have their free-text
  fields scrubbed.
- `scope_permissions` rows for the agent are deleted.
- `scopes.owner_agent_id` is nulled where it pointed to this agent.
- `audit_log` rows are scrubbed: `agent_id` cleared on actor rows, `fact_id`
  cleared on rows tied to erased facts.

```
Before: content = "Cache TTL must be 300s"   valid_until = NULL
After:  content = "[gdpr:erased:abc123]"     valid_until = "2026-04-12T..."
```

### How to trigger

**Via MCP tool (agent-driven):**
```
Call engram_gdpr_erase with agent_id="<id>" and mode="soft" or mode="hard"
```

**Via CLI:**
```bash
engram gdpr erase --agent-id agent-abc123 --mode soft
engram gdpr erase --agent-id agent-abc123 --mode hard --yes   # skip confirmation
```

**Via REST (HTTP mode):**
```bash
curl -X POST http://localhost:7474/api/gdpr/erase \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "agent-abc123", "mode": "soft"}'
```

All three entry points are restricted to the **workspace creator** (`is_creator = true`
in `~/.engram/workspace.json`).  A `PermissionError` / 403 is returned for all others.

### What is preserved after erasure

| Field | Soft | Hard |
|-------|------|------|
| Fact ID (for referential integrity) | ✅ kept | ✅ kept |
| Fact content | ✅ kept | ❌ replaced |
| Fact `valid_until` | ✅ unchanged | ❌ closed |
| `engineer` field | ❌ `[redacted]` | ❌ `[redacted]` |
| `embedding` | ✅ kept | ❌ nulled |
| `keywords`, `entities` | ✅ kept | ❌ nulled |
| Conflict rows | ✅ kept | ❌ open→dismissed |
| Conflict text fields | ❌ scrubbed | ❌ scrubbed |
| `audit_log` actor rows | ❌ agent_id nulled | ❌ agent_id nulled |

### Operator checklist before hard erase

1. **Backup first.** Hard erase is irreversible.
2. Identify the correct `agent_id` via `engram_agents` or `GET /api/agents`.
3. Confirm workspace creator status (`is_creator: true` in `~/.engram/workspace.json`).
4. Run soft erase first in staging/test if possible.
5. Keep an internal record of the erasure event (time, requester, agent erased)
   for your own compliance audit trail — Engram's audit log entry is also
   scrubbed during erasure.

## Invite Key Lifecycle

Engram workspace access is controlled by cryptographic invite keys. Every key
embeds the workspace ID, database URL, and a key generation counter in an
HMAC-signed, XOR-encrypted payload. Key rotation is the primary mechanism for
revoking access.

### Key rotation flow

1. Creator calls `engram_reset_invite_key` (MCP), `POST /api/invite-key/rotate`
   (REST), or `engram invite rotate` (CLI).
2. All **active** invite keys are **soft-revoked**: `revoked_at` is set to now,
   `grace_until` is set to `now + grace_minutes` (default 15 minutes).
3. The workspace `key_generation` counter is incremented.
4. A new invite key is generated with the updated generation counter and
   stored in the database.
5. An audit log entry (`operation = key_rotation`) is written with the old and
   new generations, grace window, reason, and actor.
6. A `invite_key.rotated` webhook event is fired to all subscribed endpoints.

### Grace period for active sessions

| Condition | Behaviour |
|-----------|-----------|
| Within grace window | Existing sessions continue uninterrupted |
| Grace window expired | Agent receives `"disconnected"` on next tool call |
| New join attempt with old key | **Rejected immediately** (grace does not apply) |

The grace window allows agents currently in the middle of a long task to
finish before being disconnected. It provides **no protection** for new
join attempts — `consume_invite_key` checks `revoked_at IS NULL` and returns
`None` for revoked keys regardless of `grace_until`.

To revoke access immediately with no grace period, use `grace_minutes=0`.

### Audit trail

Every rotation produces an `audit_log` row:

```json
{
  "operation": "key_rotation",
  "extra": {
    "old_generation": 2,
    "new_generation": 3,
    "grace_minutes": 15,
    "grace_until": "2026-04-13T02:30:00+00:00",
    "reason": "Suspected credential leak",
    "actor": "alice"
  }
}
```

Query rotation history via `engram invite history` (CLI) or
`GET /api/invite-key/history` (REST).

### Webhook payload (`invite_key.rotated`)

```json
{
  "event": "invite_key.rotated",
  "data": {
    "workspace_id": "ENG-XXXX-YYYY",
    "old_generation": 2,
    "new_generation": 3,
    "rotated_by": "alice",
    "grace_until": "2026-04-13T02:30:00+00:00",
    "reason": "Suspected credential leak"
  }
}
```

Subscribe to this event by registering a webhook with `"invite_key.rotated"` in
the `events` list, or use `"*"` to receive all events.

### Operator checklist for key rotation

1. Notify team members beforehand if using `grace_minutes=0` (no grace).
2. Set a meaningful `reason` — it appears in the audit log and rotation history.
3. Distribute the new invite key via a secure out-of-band channel.
4. Confirm all agents have reconnected by checking `GET /api/agents`.
5. Rotate quarterly as a preventive measure, not only after suspected breaches.

## Related Documentation

- [DATABASE_SECURITY.md](./DATABASE_SECURITY.md) - Database configuration and isolation
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) - Technical architecture details
- [SECURITY.md](./SECURITY.md) - General security practices