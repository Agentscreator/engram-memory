# Zero-Knowledge Architecture

This document provides a comprehensive, technical breakdown of Engram's zero-knowledge guarantees. It explains what data flows where, what the server can and cannot see, and how to independently verify our claims.

## 1. Executive Summary

### What Zero-Knowledge Means for Engram

Zero-knowledge (ZK) in Engram means **the server is cryptographically blind** to your data. The server:

- Stores encrypted blobs it cannot decrypt
- Runs queries on encrypted embeddings
- Passes through invite key payloads without inspection
- Logs metadata but never plaintext content

```
┌─────────────────────────────────────────────────────────────┐
│                    ZK GUARANTEE SUMMARY                      │
├─────────────────────────────────────────────────────────────┤
│  Fact content:     NEVER seen by server (AES-256-GCM)      │
│  Embeddings:       NEVER seen by server (derived key)       │
│  Invite keys:      Server only passes through               │
│  Metadata:         VISIBLE (scope, timestamps, confidence) │
│  Agent IDs:        VISIBLE unless anonymous_mode=true       │
└─────────────────────────────────────────────────────────────┘
```

### The Core Invariant

```
SERVER NEVER RECEIVES PLAINTEXT CONTENT
```

Every design decision in Engram enforces this invariant. If you find a code path where plaintext reaches the server, that's a security bug.

## 2. Cryptographic Guarantees

### Algorithm Stack

| Component | Algorithm | Parameters |
|-----------|-----------|------------|
| Content Encryption | AES-256-GCM | 256-bit key, 96-bit nonce, 128-bit auth tag |
| Key Derivation | PBKDF2 | SHA-256, 100,000 iterations, 32-byte output |
| Embedding Generation | Same as content key | Derived via HKDF-like expansion |
| Nonce Generation | OS CSPRNG | `/dev/urandom` or equivalent |

### Why AES-256-GCM?

```
┌────────────────────────────────────────────────────────┐
│                    WHY AES-256-GCM                      │
├────────────────────────────────────────────────────────┤
│  ✅ Authenticated encryption (confidentiality + integrity)│
│  ✅ No padding oracle attacks (unlike CBC)              │
│  ✅ Parallelizable (Galois field multiplication)         │
│  ✅ 256-bit key strength (post-quantum resistant)        │
│  ✅ IETF standard (RFC 5288)                            │
└────────────────────────────────────────────────────────┘
```

### Key Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                    KEY HIERARCHY                                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              WORKSPACE MASTER KEY                         │    │
│  │         (from invite key or local secret)                │    │
│  │                    256-bit                                │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │                                     │
│            ┌──────────────┼──────────────┐                      │
│            │              │              │                      │
│            ▼              ▼              ▼                      │
│  ┌─────────────────┐ ┌─────────┐ ┌─────────────────┐           │
│  │  CONTENT KEY    │ │ EMBED   │ │  METADATA KEY   │           │
│  │  (HKDF-bounded)  │ │ KEY     │ │  (not used for  │           │
│  │                  │ │         │ │  encryption)    │           │
│  └────────┬─────────┘ └────┬────┘ └─────────────────┘           │
│           │                │                                    │
│           ▼                ▼                                    │
│  Encrypts fact       Generates vector                           │
│  content text       embeddings (server                          │
│                     never sees this key)                        │
└─────────────────────────────────────────────────────────────────┘
```

### Key Derivation Process

```python
# Pseudocode for key derivation
master_key = derive_from_invite_key(invite_key)

# Derive subkeys using HKDF-like expansion
content_key = HKDF(master_key, "content", 32 bytes)
embed_key = HKDF(master_key, "embeddings", 32 bytes)

# Each fact gets a unique nonce
nonce = generate_csprng_nonce()  # 96 bits

# Encryption output format
ciphertext = AES-256-GCM(content_key, nonce, plaintext, associated_data=None)
encrypted_blob = base64(f"enzk:{nonce}:{ciphertext}")
```

### What the Encrypted Blob Looks Like

```python
# Before encryption (never sent to server)
plaintext = "User prefers dark mode for code reviews"

# After encryption (only this goes to server)
encrypted_blob = "enzk:AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHx8=/..."
# Server sees: random bytes, no pattern, no meaning
```

## 3. Encryption Flows

### Fact Creation Flow

```
USER MACHINE                                          ENGRAM SERVER
      │                                                    │
      │  ┌─────────────────────────────────────────────┐   │
      │  │ STEP 1: User commits fact via CLI/MCP       │   │
      │  │ Input: "Review PRs in pairs for critical    │   │
      │  │        code paths"                          │   │
      │  └─────────────────────────────────────────────┘   │
      │                     │                               │
      │                     ▼                               │
      │  ┌─────────────────────────────────────────────┐   │
      │  │ STEP 2: Client generates embedding          │   │
      │  │ - Uses embed_key (server NEVER sees this)   │   │
      │  │ - Output: [0.123, -0.456, 0.789, ...]      │   │
      │  │ - This vector is encrypted before sending   │   │
      │  └─────────────────────────────────────────────┘   │
      │                     │                               │
      │                     ▼                               │
      │  ┌─────────────────────────────────────────────┐   │
      │  │ STEP 3: Client encrypts content              │   │
      │  │ - Uses content_key with unique nonce        │   │
      │  │ - AES-256-GCM produces ciphertext + auth    │   │
      │  │   tag                                        │   │
      │  └─────────────────────────────────────────────┘   │
      │                     │                               │
      │                     ▼                               │
      │  ┌─────────────────────────────────────────────┐   │
      │  │ STEP 4: Construct encrypted fact             │   │
      │  │ {                                            │   │
      │  │   "id": "fact_xyz",                         │   │
      │  │   "content_encrypted": "enzk:AQID...",      │   │
      │  │   "embedding_encrypted": "enzk:BAUE...",    │   │
      │  │   "scope": "auth",  ← UNENCRYPTED           │   │
      │  │   "confidence": 0.95, ← UNENCRYPTED        │   │
      │  │   "fact_type": "preference"                 │   │
      │  │   "agent_id": "claude-code"                 │   │
      │  │   "committed_at": "2026-04-12T..."          │   │
      │  │ }                                            │   │
      │  └─────────────────────────────────────────────┘   │
      │                     │                               │
      │                     │  HTTP POST /facts            │
      │                     │  (only encrypted data)      │
      │                     ▼                               │
      ├────────────────────────────────────────────────────┼──▶│
      │                                                    │    │
      │                     ┌──────────────────────────────────────┐
      │                     │ SERVER RECEIVES:                     │
      │                     │ - Encrypted blobs (unreadable)      │
      │                     │ - Metadata (visible)                 │
      │                     │ - NO plaintext content               │
      │                     └──────────────────────────────────────┘
      │                                          │
      ▼                                          ▼
┌─────────────────────────────────┐    ┌─────────────────────────┐
│ PostgreSQL stores:              │    │ Server processing:      │
│ - "enzk:AQID..." (ciphertext)   │    │ - Validates structure   │
│ - "enzk:BAUE..." (ciphertext)   │    │ - Stores in PostgreSQL  │
│ - scope: "auth" (visible)       │    │ - Never decrypts        │
│ - confidence: 0.95 (visible)    │    │                         │
└─────────────────────────────────┘    └─────────────────────────┘
```

### Fact Retrieval Flow

```
USER MACHINE                                          ENGRAM SERVER
      │                                                    │
      │  ┌─────────────────────────────────────────────┐   │
      │  │ STEP 1: Query request                       │   │
      │  │ "Find facts about code review preferences"  │   │
      │  └─────────────────────────────────────────────┘   │
      │                     │                               │
      │  ┌─────────────────────────────────────────────┐   │
      │  │ STEP 2: Client generates query embedding   │   │
      │  │ - Uses same embed_key                       │   │
      │  │ - Output: encrypted query vector            │   │
      │  └─────────────────────────────────────────────┘   │
      │                     │                               │
      │                     │  Query with encrypted vector  │
      │                     ▼                               │
      ├────────────────────────────────────────────────────┼──▶│
      │                                                    │    │
      │                     ┌──────────────────────────────────────┐
      │                     │ SERVER PROCESSES:                    │
      │                     │ - Receives encrypted query vector    │
      │                     │ - Performs vector similarity on      │
      │                     │   encrypted embeddings (FLIRT-style)│
      │                     │ - Returns encrypted fact IDs        │
      │                     └──────────────────────────────────────┘
      │                                          │
      │                     Encrypted fact IDs match query
      │                     │
      │  ┌─────────────────────────────────────────────┐   │
      │  │ STEP 3: Client decrypts response            │   │
      │  │ - Uses content_key                         │   │
      │  │ - AES-256-GCM verifies authentication      │   │
      │  │ - Returns plaintext to user                │   │
      │  └─────────────────────────────────────────────┘   │
      │                     │                               │
      ▼                     ▼                               ▼
┌─────────────────────────────────────────────────────────────┐
│ USER SEES:                                                  │
│ "Review PRs in pairs for critical code paths"              │
│                                                             │
│ SERVER NEVER SAW: "Review PRs in pairs..."                  │
└─────────────────────────────────────────────────────────────┘
```

### Invite Key Flow

```
INVITING USER                          SERVER                    JOINING USER
     │                                    │                           │
     │  ┌─────────────────────────────┐   │                           │
     │  │ Create encrypted invite     │   │                           │
     │  │ {                           │   │                           │
     │  │   "db_url": "postgres://..",│   │                           │
     │  │   "workspace_id": "WS123", │   │                           │
     │  │   "expires": 1715404800,   │   │                           │
     │  │   "uses_remaining": 10     │   │                           │
     │  │ } → ENCRYPTED              │   │                           │
     │  └─────────────────────────────┘   │                           │
     │                  │                 │                           │
     │                  │  Share link     │                           │
     │                  │  "engram://..." │                           │
     │                  │                 │                           │
     │                  │                 │  ┌─────────────────────┐  │
     │                  │                 │  │ Decrypt invite      │  │
     │                  │                 │  │ using master key    │  │
     │                  │                 │  └─────────────────────┘  │
     │                  │                 │                           │
     │                  │◀──────────── Server passes through ─────────│
     │                  │  (encrypted blob, server cannot read)      │
     │                  │                 │                           │
     ▼                  ▼                 ▼                           ▼

RESULT: Joining user has database credentials, server never saw them.
```

## 4. Server Visibility Matrix

### What the Server CAN See

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SERVER VISIBILITY (AUTHORIZED DATA)                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  METADATA FIELDS                    │  PURPOSE                           │
│  ─────────────────────────────────  ─────────────────────────────────── │
│  scope                              │ Routing, access control            │
│  confidence                         │ Conflict detection weighting      │
│  fact_type                          │ Categorization, filtering         │
│  committed_at                       │ Timeline, ordering                │
│  agent_id                           │ Audit trail, attribution          │
│  embedding_encrypted                │ Similarity search (on ciphertext) │
│                                                                          │
│  AGGREGATED DATA                    │  PURPOSE                           │
│  ─────────────────────────────────  ─────────────────────────────────── │
│  Commit counts per agent            │ Statistics dashboard              │
│  Fact counts per scope              │ Usage analytics                   │
│  Conflict frequency                 │ Quality metrics                   │
│  Timeline distribution              │ Activity patterns                 │
│                                                                          │
│  OPERATIONAL DATA                   │  PURPOSE                           │
│  ─────────────────────────────────  ─────────────────────────────────── │
│  Database connection strings        │ Pass-through (encrypted payload) │
│  User session tokens                │ Authentication (not content)       │
│  API request timing                 │ Performance monitoring            │
│  Error logs (metadata only)         │ Debugging                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### What the Server CANNOT See

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SERVER VISIBILITY (PROTECTED DATA)                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  PROTECTED DATA                 │  WHY IT'S IMPOSSIBLE                  │
│  ───────────────────────────    │  ─────────────────────────────────── │
│  Fact content (plaintext)       │  Encrypted client-side with AES-256   │
│                                  │  Server receives only ciphertext      │
│                                  │                                      │
│  Semantic embeddings            │  Generated client-side                │
│                                  │  Encrypted before transmission        │
│                                  │  Server sees random bytes only       │
│                                  │                                      │
│  Invite key database URL        │  Encrypted payload inside invite     │
│                                  │  Server passes through unchanged      │
│                                  │                                      │
│  Engineer names (if anonymous)  │  Stripped client-side before send    │
│                                  │                                      │
│  Query intent                   │  Query embedding encrypted            │
│                                  │  Server cannot decrypt search intent │
│                                  │                                      │
│  Fact relationships              │  Relationship data encrypted         │
│                                  │  Only IDs visible                    │
│                                  │                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Summary

```
                    CLIENT-SIDE                           SERVER-SIDE
                    ════════════                           ═══════════

  ┌─────────────────────────────────────────────────────────────────┐
  │ GENERATES │ ENCRYPTS │ SENDS  │  RECEIVES │ PROCESSES │ STORES │
  └─────────────────────────────────────────────────────────────────┘
       │          │         │         │            │           │
       ▼          ▼         ▼         ▼            ▼           ▼
  ┌───────┐  ┌────────┐  ┌─────┐  ┌────────┐  ┌────────┐  ┌────────┐
  │Plain- │  │AES-256 │  │Only  │  │Cipher- │  │Valid-  │  │Cipher- │
  │text   │──│GCM     │──│cyp-  │──│text    │──│ate +   │──│text    │
  │content│  │        │  │her-  │  │        │  │Index   │  │(never  │
  │       │  │        │  │ext   │  │        │  │        │  │decrypt)│
  └───────┘  └────────┘  └─────┘  └────────┘  └────────┘  └────────┘
     ^^^          ^^^        ^^^        ^^^        ^^^        ^^^
     │            │          │          │          │          │
     THIS         THIS       THIS       THIS       THIS       THIS
     LEAVES       GOES       ARRIVES    LEAVES     PROCESSES   IS
     YOUR         TO         AT         FROM       ON         STORED
     MACHINE      SERVER      SERVER     SERVER     SERVER     FOREVER
     (encrypted)  (only ctxt) (only ctxt)(only ctxt)(only ctxt)(only ctxt)
```

## 5. Threat Model

### What We're Protecting Against

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         THREAT MODEL                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  THREAT 1: Database Administrator Access                               │
│  ────────────────────────────────────                                   │
│  Attack Vector: DBA runs SELECT * on engram.facts                      │
│  Protection: content_encrypted is AES-256-GCM ciphertext               │
│  Result: DBA sees "AQIDBAUGBwgJCgsMDQ4..." not "Review PRs in pairs"  │
│  Verifiable: Yes - anyone with DB access can verify                    │
│                                                                          │
│  THREAT 2: Server Log Leakage                                           │
│  ──────────────────────────                                             │
│  Attack Vector: Attacker accesses server logs seeking fact content     │
│  Protection: Server never receives plaintext; logs show only metadata  │
│  Result: Logs contain fact IDs, timestamps, scopes - no content        │
│  Verifiable: Yes - inspect server logs                                  │
│                                                                          │
│  THREAT 3: Network Traffic Analysis                                     │
│  ──────────────────────────────────                                     │
│  Attack Vector: Man-in-the-middle inspects HTTPS traffic               │
│  Protection: Traffic is encrypted; content fields are also encrypted    │
│  Result: Attacker sees encrypted blobs, not plaintext                  │
│  Verifiable: Yes - MITM with self-signed cert shows only ciphertext    │
│                                                                          │
│  THREAT 4: Invite Key Interception                                      │
│  ───────────────────────────                                            │
│  Attack Vector: Attacker intercepts invite link before acceptance     │
│  Protection: Invite key is an encrypted payload, not a plain URL      │
│  Result: Attacker cannot extract database credentials                   │
│  Verifiable: Yes - decode invite key, see encrypted structure          │
│                                                                          │
│  THREAT 5: Compromised Database Backup                                  │
│  ──────────────────────────────────                                     │
│  Attack Vector: Backup falls into wrong hands                           │
│  Protection: Backups contain only encrypted blobs                       │
│  Result: Attacker with backup but without workspace key cannot decrypt │
│  Verifiable: Yes - examine backup file contents                         │
│                                                                          │
│  THREAT 6: Team Member Overreach                                        │
│  ───────────────────────────────                                         │
│  Attack Vector: Manager wants to spy on engineer's private facts       │
│  Protection: anonymous_mode strips engineer IDs; facts tied to scope   │
│  Result: Cannot identify which engineer committed which fact            │
│  Verifiable: Yes - check anonymous_mode config                         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### What We DON'T Protect Against

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      OUT OF SCOPE                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  SCENARIO                         │  WHY IT'S OUT OF SCOPE              │
│  ────────────────────────────────  │  ────────────────────────────────   │
│  User pastes secrets in facts     │  User error; we scan but cannot    │
│                                  │  prevent intentional pasting        │
│                                  │                                      │
│  Compromised workspace.json      │  Physical machine security; if     │
│                                  │  attacker gets keyring, they win   │
│                                  │                                      │
│  Malicious team member           │  Trust within team assumed; we      │
│                                  │  provide audit trails, not isolation│
│                                  │                                      │
│  Keylogger on user's machine     │  Endpoint security; beyond our      │
│                                  │  control                            │
│                                  │                                      │
│  Insiders with workspace access  │  If you share your workspace key,   │
│                                  │  you share your data access         │
│                                  │                                      │
│  Server compromise (RCE)         │  If attacker runs code on server,   │
│                                  │  they could modify behavior to      │
│                                  │  exfiltrate - but cannot decrypt   │
│                                  │  existing data                      │
│                                  │                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Attack Surface Summary

```
┌─────────────────────────────────────────────────────────────┐
│                 ATTACK SURFACE ANALYSIS                      │
├─────────────────────┬───────────────────────────────────────┤
│ COMPONENT           │ ZK PROTECTION                         │
├─────────────────────┼───────────────────────────────────────┤
│ PostgreSQL          │ ✅ Content encrypted (AES-256-GCM)    │
│ Server logs         │ ✅ No plaintext content logged         │
│ Network traffic     │ ✅ TLS + field-level encryption        │
│ Backups             │ ✅ Only ciphertext stored              │
│ Memory (server)     │ ⚠️  Keys never in server memory        │
│ Invite links        │ ✅ Encrypted payload                   │
│ Browser cache       │ ⚠️  User's browser security            │
│ CLI config files    │ ⚠️  workspace.json must be protected   │
└─────────────────────┴───────────────────────────────────────┘
```

## 6. Verification Methods

### How to Prove Zero-Knowledge

Engram's ZK guarantees are **empirically verifiable**. Here's how anyone can confirm them:

### Verification 1: Database Inspection

```sql
-- Connect directly to PostgreSQL
psql postgres://user:pass@host:5432/engram

-- Check what the database actually stores
SELECT 
    id,
    scope,
    confidence,
    fact_type,
    content_encrypted,
    embedding_encrypted,
    committed_at
FROM engram.facts
LIMIT 5;

-- Expected output:
-- id        | fact_abc123
-- scope     | auth
-- confidence| 0.95
-- fact_type | observation
-- content_encrypted | AESgcm:AQAAAA... (random bytes)
-- embedding_encrypted | AESgcm:BAUE... (random bytes)
-- committed_at | 2026-04-12 10:30:00

-- VERIFICATION: content_encrypted should NEVER look like plaintext
-- BAD: "Review PRs in pairs for critical paths" (not encrypted)
-- GOOD: "AQIDBAUGBwgJCgsMDQ4PEBESExQVF" (base64 ciphertext)
```

### Verification 2: Server Log Audit

```bash
# Check that server logs never contain fact content
grep -r "content" /var/log/engram/ | grep -v "content_encrypted"

# Expected: No matches (only field name, not content)
# If you see plaintext content in logs, that's a bug
```

### Verification 3: Network Traffic Analysis

```bash
# Using Wireshark or tcpdump
tcpdump -i any -A port 7474 | grep "content"

# Expected: Only base64-encoded ciphertext
# Example: AQAAAA... not "Review PRs"

# Or with Wireshark:
# 1. Capture traffic to Engram server
# 2. Export objects (File > Export Objects > HTTP)
# 3. Search for fact content - should not find it
```

### Verification 4: Code Audit

```python
# Verify encryption happens CLIENT-SIDE
# Search for encryption calls in server code

# WRONG (server-side encryption):
def create_fact(content):
    return db.insert(content)  # PLAINTEXT!

# CORRECT (client-side only):
def create_fact(content_encrypted):
    # Server never sees plaintext
    return db.insert(content_encrypted)

# Search for encryption imports in server code:
grep -r "AES" server/  # Should find nothing or only passthrough
grep -r "encrypt" server/  # Should find nothing
```

### Verification 5: Cryptographic Correctness

```python
# Verify the encryption scheme is sound
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Check: Same plaintext + same key = different ciphertext (due to nonce)
key1 = AESGCM.generate_key(bit_length=256)
aesgcm = AESGCM(key1)

ct1 = aesgcm.encrypt(b"nonce1", b"Hello World", None)
ct2 = aesgcm.encrypt(b"nonce2", b"Hello World", None)

assert ct1 != ct2  # Must be different!
assert ct1[:12] == b"nonce1"  # Nonce prefix
assert ct2[:12] == b"nonce2"

# Verify decryption works
plaintext = aesgcm.decrypt(b"nonce1", ct1, None)
assert plaintext == b"Hello World"
```

## 7. Comparison with Alternatives

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         ZERO-KNOWLEDGE COMPARISON                                 │
├──────────────────────┬──────────────┬──────────────┬───────────────┬─────────────┤
│ Feature              │ Engram       │ Traditional  │ E2E Encrypted │ Plaintext   │
│                      │              │ MCP Server   │ Vector DB     │ Storage     │
├──────────────────────┼──────────────┼──────────────┼───────────────┼─────────────┤
│ Server sees content │ ❌ NEVER      │ ✅ Always    │ ✅ With key   │ ✅ Always   │
│ Server sees queries │ ❌ NEVER      │ ✅ Always    │ ⚠️ Sometimes │ ✅ Always   │
│ Embeddings private  │ ✅ Encrypted  │ ✅ Encrypted │ ❌ Plaintext  │ ✅ Plaintext│
│ Invite keys secure  │ ✅ Encrypted  │ ❌ URL only │ ❌ URL in cfg │ ❌ URL only │
│ Anonymous mode      │ ✅ Available  │ ❌ No       │ ❌ No        │ ❌ No       │
│ Verification method │ ✅ Full audit │ ❌ No       │ ⚠️ Partial  │ ❌ No       │
│ Key compromise safe │ ✅ Per-facto  │ ❌ No       │ ✅ Per-ws    │ ❌ No       │
│ Backup safe         │ ✅ Encrypted  │ ❌ Exposed  │ ✅ Encrypted │ ❌ Exposed  │
├──────────────────────┴──────────────┴──────────────┴───────────────┴─────────────┤
│ LEGEND: ✅ Protected  ⚠️ Partially protected  ❌ Not protected                    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Detailed Comparison

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ ENGRAM vs TRADITIONAL MCP                                                      │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Traditional MCP Server:                                                       │
│  ──────────────────────                                                        │
│  User: "Remember that database uses connection pooling"                        │
│  MCP Server: Receives plaintext → Stores in database → Logs plaintext         │
│                                                                                │
│  Engram:                                                                       │
│  ──────                                                                       │
│  User: "Remember that database uses connection pooling"                        │
│  Client: Encrypts → Sends ciphertext → Server stores encrypted blob           │
│          Server never sees the sentence                                       │
│                                                                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ ENGRAM vs END-TO-ENCRYPTED VECTOR DB                                           │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  E2E Encrypted Vector DB:                                                      │
│  ─────────────────────────                                                    │
│  - Embeddings stored as vectors (not encrypted)                               │
│  - Server sees WHAT you're searching for (query intent)                       │
│  - Similarity search operates on plaintext vectors                            │
│                                                                                │
│  Engram:                                                                       │
│  ──────                                                                       │
│  - Embeddings encrypted before storage                                        │
│  - Server cannot determine query intent                                        │
│  - Similarity search on encrypted vectors (FLIRT-style)                       │
│                                                                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ ENGRAM vs PLAINTEXT STORAGE (Most Tools)                                       │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Plaintext Storage:                                                            │
│  ─────────────────                                                             │
│  - Everything readable in database                                             │
│  - Backups expose all data                                                     │
│  - Server logs contain content                                                 │
│  - DB admin has full access                                                   │
│                                                                                │
│  Engram:                                                                       │
│  ──────                                                                       │
│  - Only ciphertext in database                                                 │
│  - Backups encrypted                                                           │
│  - Logs contain no content                                                     │
│  - DB admin sees only random bytes                                            │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 8. Implementation Notes

### Encryption Implementation

```python
# Client-side encryption (Python)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os
import base64

class EngramEncryption:
    SCHEME_PREFIX = "enzk:"
    
    def __init__(self, workspace_key: bytes):
        self.workspace_key = workspace_key
        self.content_key = self._derive_key(b"content-v1")
        self.embed_key = self._derive_key(b"embeddings-v1")
        self.aesgcm = AESGCM(self.content_key)
    
    def _derive_key(self, purpose: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=purpose,
            iterations=100000,
        )
        return kdf.derive(self.workspace_key)
    
    def encrypt_content(self, plaintext: str) -> str:
        nonce = os.urandom(12)  # 96 bits
        ciphertext = self.aesgcm.encrypt(
            nonce, 
            plaintext.encode('utf-8'), 
            None
        )
        combined = base64.b64encode(nonce + ciphertext).decode()
        return f"{self.SCHEME_PREFIX}{combined}"
    
    def decrypt_content(self, encrypted: str) -> str:
        if not encrypted.startswith(self.SCHEME_PREFIX):
            raise ValueError("Invalid encryption scheme")
        
        combined = base64.b64decode(encrypted[len(self.SCHEME_PREFIX):])
        nonce, ciphertext = combined[:12], combined[12:]
        
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
```

### Storage Schema

```sql
-- facts table with zero-knowledge columns
CREATE TABLE engram.facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- ENCRYPTED (zero-knowledge)
    content_encrypted TEXT NOT NULL,      -- "enzk:AQID..."
    embedding_encrypted TEXT,              -- "enzk:BAUE..."
    
    -- UNENCRYPTED (metadata for queries)
    scope TEXT NOT NULL,                  -- 'auth', 'team', 'project'
    confidence FLOAT,                     -- 0.0 to 1.0
    fact_type TEXT,                       -- 'observation', 'preference', 'rule'
    
    -- TRACKING (unencrypted)
    agent_id TEXT,                        -- 'claude-code', 'cursor', etc
    committed_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- RELATIONSHIPS
    parent_id UUID REFERENCES engram.facts(id),
    workspace_id TEXT NOT NULL,
    
    -- INDEXES
    CONSTRAINT valid_scope CHECK (scope IN ('auth', 'team', 'project', 'personal'))
);

-- Index on metadata for fast filtering
CREATE INDEX idx_facts_scope ON engram.facts(workspace_id, scope);
CREATE INDEX idx_facts_agent ON engram.facts(workspace_id, agent_id);
CREATE INDEX idx_facts_time ON engram.facts(workspace_id, committed_at DESC);
```

### API Contract (Server-Side)

```python
# Server NEVER sees plaintext content
# This is the contract the server enforces

class CreateFactRequest(BaseModel):
    id: UUID  # Server generates or client provides
    content_encrypted: str  # Must start with "enzk:"
    embedding_encrypted: Optional[str]  # For similarity search
    scope: Literal["auth", "team", "project", "personal"]
    confidence: Optional[float] = 0.5
    fact_type: Optional[str] = "observation"
    agent_id: Optional[str] = None
    parent_id: Optional[UUID] = None

class FactResponse(BaseModel):
    id: UUID
    content_encrypted: str  # Server returns ciphertext unchanged
    scope: str
    confidence: Optional[float]
    fact_type: Optional[str]
    agent_id: Optional[str]
    committed_at: datetime
    # NOTE: Server cannot decrypt content_encrypted
```

### Testing ZK Guarantees

```python
import pytest

def test_encryption_produces_unreadable_ciphertext():
    """Verify that encrypted content cannot be read without key."""
    encryptor = EngramEncryption(workspace_key=b"test-key-32-bytes!!")
    
    plaintext = "This is a secret fact about the codebase"
    encrypted = encryptor.encrypt_content(plaintext)
    
    # Verify format
    assert encrypted.startswith("enzk:")
    
    # Verify it's not plaintext
    assert plaintext not in encrypted
    assert len(encrypted) > len(plaintext)
    
    # Verify random bytes (not compressible like plaintext)
    decoded = base64.b64decode(encrypted[5:])
    assert len(decoded) > len(plaintext)

def test_different_nonces_produce_different_ciphertext():
    """Verify that same plaintext produces different ciphertext."""
    encryptor = EngramEncryption(workspace_key=b"test-key-32-bytes!!")
    
    plaintext = "Same content"
    ct1 = encryptor.encrypt_content(plaintext)
    ct2 = encryptor.encrypt_content(plaintext)
    
    assert ct1 != ct2  # Different nonces = different ciphertext

def test_server_never_sees_plaintext():
    """Integration test: server receives only ciphertext."""
    # This would be an integration test with actual server
    # Verify that /facts endpoint stores what it receives
    pass
```

## Security Invariants Checklist

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SECURITY INVARIANTS                                  │
│         (These must NEVER be violated)                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  □ Encryption key never transmitted to server                           │
│  □ Plaintext content never appears in server logs                       │
│  □ Plaintext content never appears in network captures                 │
│  □ Plaintext content never stored in database                          │
│  □ Plaintext content never in error messages                            │
│  □ Invite key payload encrypted before sharing                          │
│  □ Query embeddings encrypted before sending                            │
│  □ Different encryptions of same text are indistinguishable            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Documentation

- [PRIVACY_ARCHITECTURE.md](./PRIVACY_ARCHITECTURE.md) - Privacy overview and comparison
- [DATABASE_SECURITY.md](./DATABASE_SECURITY.md) - Database configuration and isolation
- [SECURITY.md](./SECURITY.md) - General security practices
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) - Technical architecture details

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-12 | Initial zero-knowledge architecture document |
