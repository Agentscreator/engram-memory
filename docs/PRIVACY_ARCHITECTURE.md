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

## Related Documentation

- [DATABASE_SECURITY.md](./DATABASE_SECURITY.md) - Database configuration and isolation
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) - Technical architecture details
- [SECURITY.md](./SECURITY.md) - General security practices