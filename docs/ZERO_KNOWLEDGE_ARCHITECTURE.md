# Zero-Knowledge Architecture

This document provides technical transparency on how Engram enforces zero-knowledge guarantees — verifiable proof that the server never sees your data.

## Core Invariant

**The Engram server never receives plaintext.** All encryption and decryption happens client-side. The server operates exclusively on encrypted data it cannot decrypt.

## What the Server Can and Cannot Access

| What Server Sees | What Server Cannot See |
|-----------------|------------------------|
| Fact metadata (scope, confidence, timestamps) | Fact content (always encrypted) |
| Conflict patterns (from encrypted embeddings) | Embedding vectors (encrypted) |
| Aggregate statistics | Query intent or results |
| Workspace IDs | Database URLs in invite keys |

## Cryptographic Guarantees

- **Algorithm:** AES-256-GCM (authenticated encryption)
- **Key Derivation:** PBKDF2 with SHA-256, 100,000 iterations
- **Key Hierarchy:**
  - Workspace Master Key → derives all child keys
  - Content Key → encrypts fact content
  - Embedding Key → generates semantic vectors

## Encryption Flow

```
User's Machine
      │
      ▼
┌─────────────────────────┐
│ 1. Generate embedding   │
│    (client-side only)   │
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
│ 3. Send encrypted blob  │
│    to PostgreSQL        │
└─────────────────────────┘
      │
      ▼
  PostgreSQL
  (sees only ciphertext)
```

## Threat Model

| Threat | Protection |
|--------|------------|
| Database admin reads facts | Content encrypted client-side |
| Server logs leak content | Server never receives plaintext |
| Invite key interception | Key is encrypted, not signed |
| Backup exposure | Backups contain only encrypted blobs |

## Verification Methods

1. **Database inspection:**
   ```sql
   SELECT content_encrypted FROM engram.facts LIMIT 1;
   -- Returns only: 'AESgcm:AQAAAA...' (unreadable)
   ```

2. **Network analysis:**
   ```bash
   tcpdump -i any -A | grep "fact_content"
   -- Only sees base64-encoded ciphertext
   ```

3. **Log audit:**
   ```bash
   grep -r "fact_content" /var/log/engram/
   -- Should return nothing
   ```

## Comparison

| Feature | Engram | Traditional MCP | E2E Vector DB |
|---------|--------|-----------------|--------------|
| Server sees plaintext | Never | Yes | No |
| Embeddings encrypted | Yes | Yes | Optional |
| Invite keys encrypted | Yes | No | No |

## Related Documentation

- [Privacy Architecture](./PRIVACY_ARCHITECTURE.md) — Full privacy guarantees
- [Database Security](./DATABASE_SECURITY.md) — Database configuration
- [Client-Side Encryption](./CLIENT_SIDE_ENCRYPTION.md) — Implementation details
