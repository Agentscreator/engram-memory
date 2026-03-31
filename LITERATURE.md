# Literature

PDFs are in [`./papers/`](./papers/).

---

## [1] Multi-Agent Memory from a Computer Architecture Perspective: Visions and Challenges Ahead

**Authors:** Zhongming Yu, Naicheng Yu, Hejia Zhang, Wentao Ni, Mingrui Yin, Jiaying Yang, Yujie Zhao, Jishen Zhao
**Affiliations:** UC San Diego, Georgia Tech
**Venue:** Architecture 2.0 Workshop, March 23, 2026, Pittsburgh, PA
**ArXiv:** [2603.10062](https://arxiv.org/abs/2603.10062)
**File:** [`papers/2603.10062v1.pdf`](papers/2603.10062v1.pdf)

### Summary

This position paper — the direct intellectual foundation for Engram — frames multi-agent memory as a **computer architecture problem**. The central observation is that LLM agent systems are hitting a wall that looks exactly like the memory bottleneck in classical hardware: performance limited not by compute but by bandwidth, hierarchy, and consistency.

**Three-layer memory hierarchy:**
- *I/O layer* — interfaces ingesting audio, text, images, network calls (e.g., MCP)
- *Cache layer* — fast, limited-capacity short-term storage: compressed context, recent tool calls, KV caches, embeddings
- *Memory layer* — large-capacity long-term storage: full dialogue history, vector DBs, graph DBs

**Two missing protocols:**
1. *Agent cache sharing* — no principled protocol exists for one agent's cached artifacts to be transformed and reused by another (analogous to cache transfers in multiprocessors)
2. *Agent memory access control* — permissions, scope, and granularity for reading/writing another agent's memory remain under-specified

**Central claim:** The most pressing open challenge is **multi-agent memory consistency**. In single-agent settings, consistency means temporal coherence — new facts must not contradict established ones. In multi-agent settings, the problem compounds: multiple agents read from and write to shared memory concurrently, raising classical challenges of *visibility*, *ordering*, and *conflict resolution*. The difficulty is harder than hardware because memory artifacts are semantic and heterogeneous (evidence, tool traces, plans), and conflicts are often semantic and coupled to environment state.

**Relevance to Engram:** Engram directly implements the consistency layer this paper identifies as the field's most urgent gap. `engram_commit` is the shared write; `engram_query` is the read; `engram_conflicts` is the conflict detection mechanism. The paper's vocabulary — shared vs. distributed memory, hierarchy layers, consistency models — is the conceptual language of this project.

---

## [2] A-Mem: Agentic Memory for LLM Agents

**Authors:** Wujiang Xu, Zujie Liang, Kai Mei, Hang Gao, Juntao Tan, Yongfeng Zhang
**Affiliations:** Rutgers University, Independent Researcher, AIOS Foundation
**ArXiv:** [2502.12110](https://arxiv.org/abs/2502.12110) (v11, Oct 2025)
**File:** [`papers/2502.12110v11.pdf`](papers/2502.12110v11.pdf)

### Summary

A-Mem proposes a **Zettelkasten-inspired agentic memory system** that dynamically organizes memories without predefined schemas or fixed workflows. Each memory is stored as a structured note with content, timestamp, keywords, tags, contextual description, embedding, and links. Three-phase operation: note construction, link generation, memory evolution. Outperforms MemGPT, MemoryBank, and ReadAgent on LoCoMo benchmark.

**Relevance to Engram:** A-Mem solves *single-agent* memory organization. It has no notion of shared state or cross-agent consistency. Its note structure is instructive for how Engram enriches committed facts with semantic metadata.

---

## [3] MIRIX: Multi-Agent Memory System for LLM-Based Agents

**Authors:** Yu Wang, Xi Chen
**Affiliation:** MIRIX AI (Yu Wang: UCSD, Xi Chen: NYU Stern)
**ArXiv:** [2507.07957](https://arxiv.org/abs/2507.07957) (v1, Jul 2025)
**File:** [`papers/2507.07957v1.pdf`](papers/2507.07957v1.pdf)

### Summary

MIRIX proposes a modular, multi-agent memory system organized around six specialized memory types with a Meta Memory Manager handling routing. SOTA 85.4% on LOCOMO. Its multi-agent architecture is internal (multiple agents managing one user's memory), not cross-team.

**Relevance to Engram:** MIRIX is the state-of-the-art in comprehensive single-user memory architecture. Engram addresses what MIRIX does not: what happens when two engineers' agents independently commit contradictory facts about the same codebase.

---

## [4] Memory in the Age of AI Agents: A Survey

**Authors:** Yuyang Hu, Shichun Liu, Yanwei Yue, Guibin Zhang, et al.
**Affiliations:** NUS, Renmin University, Fudan, Peking, NTU, Tongji, UCSD, HKUST(GZ), Griffith, Georgia Tech, OPPO, Oxford
**ArXiv:** [2512.13564](https://arxiv.org/abs/2512.13564) (v2, Jan 2026)
**File:** [`papers/2512.13564v2.pdf`](papers/2512.13564v2.pdf)

### Summary

The most comprehensive survey of agent memory as of early 2026. Confirms that shared memory for multi-agent systems is an open frontier (Section 7.5) and that conflict detection and resolution are unsolved. The survey's taxonomy gives Engram a precise vocabulary: Engram stores *factual memory* in a *flat token-level* form with *append-only formation* and *explicit conflict evolution*.

---

## [30] Zep: A Temporal Knowledge Graph Architecture for Agent Memory (Round 3)

**Authors:** Preston Rasmussen, Pavlo Paliychuk, Travis Jewett, Daniel Chalef (Zep AI)
**ArXiv:** [2501.13956](https://arxiv.org/abs/2501.13956) (Jan 2025)
**GitHub:** [getzep/graphiti](https://github.com/getzep/graphiti)

### Summary

Graphiti is a temporally-aware knowledge graph engine for AI agent memory. Its key architectural contribution relevant to Engram is **bitemporal modeling**: every node and edge carries both *valid time* (when the fact was true in the world) and *transaction time* (when the system learned it). This provides full auditability and point-in-time queryability without any separate archive mechanism.

**Critical insight for Round 3:** Graphiti uses temporal edge invalidation — when a conflict is detected, the old edge's `invalid_at` timestamp is set, preserving historical record while marking it as not current. This is the same primitive as Engram's `valid_until` but applied to a graph structure.

**Why not just use Graphiti?** Graphiti requires Neo4j (external service, ~1GB RAM, JVM). Engram's design philosophy is local-first with `pip install`. Graphiti's primary use case is rich knowledge graph traversal; Engram's is consistency checking. The bitemporal validity insight transfers; the implementation does not.

**Influence on Round 3 rewrite:** Graphiti's `valid_from`/`valid_until` model directly inspired the collapse of Round 2's four versioning mechanisms (`superseded_by`, `facts_archive`, `utility_score`, version chain) into a single temporal invariant.

---

## [31] NLI Domain Shift on Technical Facts (Round 3 Finding)

**Sources:** Research synthesis from production NLI deployment literature, 2024–2025.

### Summary

Cross-encoder NLI models (`cross-encoder/nli-deberta-v3-base`) achieve high accuracy on general-domain benchmarks (SNLI/MNLI) but suffer significant performance degradation when applied to technical domain text. Root causes:

1. **Vocabulary mismatch:** SNLI/MNLI uses everyday conversational English. Codebase facts contain domain-specific jargon, numeric constraints, version identifiers, and API terminology not present in training data.
2. **Structural mismatch:** NLI benchmarks are typically 1-2 sentence premise/hypothesis pairs. Codebase facts may be structured claims with embedded entity references.
3. **Label artifact learning:** NLI models learn to classify based on trigger words ("not", "never", "no") rather than logical inference — unreliable in technical contexts where these words have different distributions.

**The 92% accuracy claim cited in Round 2 is on benchmark data, not production technical facts.**

**Influence on Round 3 rewrite:** NLI demoted from *judge* to *signal*. Deterministic entity and numeric rules (Tier 0, Tier 2) handle the majority of high-confidence technical contradictions. NLI handles natural language semantic contradictions — its genuine strength. Threshold is locally calibrated via feedback loop.

---

## [32] SQLite WAL Mode Concurrency Limits Under Concurrent Writes (Round 3 Finding)

**Sources:** SQLite documentation, PowerSync engineering blog, benchmark literature.

### Summary

SQLite WAL mode enables concurrent reads during writes, but enforces **strict single-writer serialization**: only one connection can write at a time. If NLI inference (~300ms) runs inside the write transaction, the write lock is held for 300ms. With 10 concurrent agents attempting commits, throughput collapses to ~3 commits/second.

**This is a fatal bottleneck for multi-agent use if detection blocks the write path.**

**Influence on Round 3 rewrite:** Conflict detection fully decoupled from the write path. The write lock is held only for the `INSERT INTO facts` statement (~1ms). Detection runs in a background asyncio worker. Throughput at 10 concurrent agents: ~100 commits/second (SQLite WAL insert rate).

---

## [33] Byzantine Fault Tolerance: Overhead vs. Necessity Assessment (Round 3 Finding)

**Sources:** BFT literature synthesis, multi-agent coordination research, 2025 industry practice.

### Summary

BFT consensus protocols (PBFT, HotStuff) are designed for open adversarial networks with unknown participants. They require O(n²) message complexity, high latency, and significant implementation overhead. For a **permissioned, private, trusted-agent network** (Engram's target environment), BFT provides zero practical benefit and catastrophic complexity cost.

Industry consensus (2025): start with the simplest possible coordination mechanism. For trust models that assume good-faith participants with occasional crashes, SQLite's WAL mode provides sufficient durability (crash fault tolerance). BFT is needed when participants are unknown or actively malicious.

**Influence on Round 3 rewrite:** BFT removed entirely. Rate limiting + agent reliability scoring + source corroboration provide sufficient protection against accidental poisoning. Full adversarial attack resistance is explicitly out of scope for the initial Engram implementation.

---

## [34] Quorum Commits: Coordination Tax vs. Solo Developer Reality (Round 3 Finding)

**Sources:** Multi-agent coordination literature, 2025 industry analysis.

### Summary

Quorum-based commit protocols require a minimum number of independent agents to ratify a fact before it is considered trusted. For a **single-developer workflow** (the majority case for Engram's initial users), no quorum is ever achievable — the developer runs one agent at a time. Quorum commits, as proposed in Round 2, would make Engram non-functional for its primary user.

The underlying goal (single-source facts are less trusted) is achievable without the quorum mechanism: track `corroborating_agents` count as metadata, downweight single-source facts in query scoring.

**Influence on Round 3 rewrite:** Quorum commits removed. Source corroboration count tracked as a metadata signal, not an access gate.

---

## Landscape at a Glance

| Paper | Scope | Consistency | Conflict Detection | Year |
|---|---|---|---|---|
| Yu et al. [1] | Architecture framing | Named as #1 open problem | Not implemented | 2026 |
| Xu et al. [2] (A-Mem) | Single-agent memory organization | Temporal coherence only | No | 2025 |
| Wang & Chen [3] (MIRIX) | Single-user multi-component memory | Within one user's store | No | 2025 |
| Hu et al. [4] (Survey) | Full landscape | Flagged as unsolved frontier | No | 2026 |
| Rasmussen et al. [30] (Zep/Graphiti) | Single-agent temporal KG | Bitemporal edge invalidation | Implicit (supersession) | 2025 |
| **Engram** | **Multi-agent shared memory** | **Cross-agent fact consistency** | **Yes (`engram_conflicts`)** | **2026** |

### Round 3 Structural Simplifications vs. Round 2

| Round 2 Mechanism | Round 3 Replacement | Net Change |
|---|---|---|
| `superseded_by TEXT` pointer | `valid_until` timestamp | Removed 1 column |
| `facts_archive` separate table | `WHERE valid_until < CUTOFF` predicate | Removed 1 table |
| `utility_score REAL` decay field | `WHERE valid_from < CUTOFF` predicate | Removed 1 column |
| Version chain pointer chasing | `WHERE lineage_id = X ORDER BY valid_from` | Removed pointer |
| BFT consensus protocol | Removed | Removed 1 major subsystem |
| Graph database requirement | Removed | Removed 1 external dependency |
| Quorum commit gating | Source corroboration metadata | Simplified mechanism |
| Confidence in scoring formula | Removed from formula | Reduced noise |
| NLI as judge | NLI as signal + calibration loop | More robust |
| Detection in write path | Detection in background worker | Fixed fatal bottleneck |

---

# MCP Ecosystem Learnings

The following findings come from studying the MCP servers that achieved real production adoption, the MCP specification evolution, and production security guidance. These shaped Engram's tool design, transport, deployment model, and security posture.

---

## Context7 (Upstash) — 44k GitHub Stars, 240k Weekly npm Downloads

**Source:** [Hands-on Architects analysis](https://handsonarchitects.com/blog/2026/what-makes-mcp-server-successful/) (Feb 2026)

The most successful MCP server by adoption. Provides real-time documentation to AI coding assistants. Two tools only: `resolve-library-id` and `query-docs`.

Key architectural decisions relevant to Engram:

- Tool descriptions carry embedded behavioral guidance: privacy warnings, call frequency limits ("Do not call more than 3 times per question"), query quality examples (good vs bad queries), and structured selection criteria. The LLM reads these at tool discovery and follows them.
- Server-side reranking reduced token consumption by 65% and latency by 38% vs. returning raw results for the LLM to filter.
- Zero-setup deployment: one line of JSON config (`npx -y @upstash/context7-mcp`).
- Privacy by design: user code never leaves the local machine. Only reformulated queries are sent to the API.
- DiskANN for cost-effective vector storage (indexes on disk, not RAM).
- ThoughtWorks Technology Radar listed Context7 in its "Tools" section.

**Impact on Engram:** Engram adopts the behavioral guidance pattern for tool descriptions, server-side ranking, zero-setup local deployment via `uvx`, and the privacy-by-design principle (NLI and embedding models run locally).

---

## Block's Playbook — 60+ Internal MCP Servers

**Source:** [Block Engineering Blog](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers) (Jun 2025)

Key principles from building MCP servers at production scale:

- Design top-down from workflows, not bottom-up from API endpoints. Combine multiple internal calls into single high-level tools.
- Tool names, descriptions, and parameters are prompts for the LLM. Use Pydantic models with field descriptions.
- Token budget management: check output size before returning, truncate or paginate large responses, raise actionable errors for oversized content.
- Prompt prefix caching: avoid injecting dynamic data into tool descriptions (breaks cache).
- Goose (Block's open-source agent) raises tool execution errors for files over 400KB with actionable recovery suggestions.

**Impact on Engram:** `engram_query` caps responses at ~4000 tokens. `engram_commit` uses Pydantic validation. Tool descriptions include good/bad query examples and call frequency limits.

---

## MCP Specification Evolution (2024–2026)

**Sources:** [MCP Specification](https://modelcontextprotocol.io), [Anthropic AAIF announcement](https://www.anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation) (Dec 2025), [ForgeCode spec analysis](https://forgecode.dev/blog/mcp-spec-updates/) (Jun 2025)

- MCP donated to Linux Foundation's Agentic AI Foundation (Dec 2025). OpenAI, Google DeepMind, Microsoft, AWS, Cloudflare joined as founding members. 97M cumulative SDK downloads. 13k+ servers on GitHub.
- Streamable HTTP replaced SSE as recommended remote transport (spec 2025-03-26). More flexible, production-ready, supports both stateless and stateful modes.
- OAuth 2.1 with PKCE for remote server auth (spec 2025-06-18). Servers classified as OAuth 2.0 Resource Servers. Protected Resource Metadata (RFC 9728) for authorization server discovery. Resource parameter (RFC 8707) for token binding.
- Tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`) for client-side safety decisions (spec 2025-11-25).
- Structured JSON output (`structuredContent`) for machine-readable tool results.
- Resource links (`resource_link` type) for lazy-loading large data.
- `MCP-Protocol-Version` header required on all HTTP requests (spec 2025-06-18).
- JSON-RPC batching removed (breaking change in 2025-06-18).

**Impact on Engram:** Engram supports both stdio (local) and Streamable HTTP (team/remote). Auth follows the OAuth 2.0 Resource Server model. All tools carry annotations. Bearer tokens as MVP, full OAuth 2.1 as future work.

---

## Production MCP Security Best Practices

**Sources:** [Aptori](https://www.aptori.com/blog/mcp-server-best-practices) (Mar 2026), [Microsoft OWASP MCP Top 10](https://microsoft.github.io/mcp-azure-security-guide/)

- Validate all inputs — LLM output is untrusted. Use Pydantic schemas, parameterized queries.
- Enforce authorization per tool, not just per connection. Bind access to identity.
- One tool, one responsibility. Ambiguous tools get misused by LLMs.
- Full observability: log every tool call with identity, arguments, duration.
- Validate behavior, not just inputs. Identity-to-object relationships must be enforced.
- Token confusion attacks: bind tokens to specific server instances (audience claim).
- HTTPS required for any non-localhost deployment.

**Impact on Engram:** All tool inputs validated via Pydantic. Parameterized SQL only. Scope permissions enforced per tool call. Tool calls logged with agent identity and duration. Tokens bound to server instance.

---

## Top MCP Servers by Adoption (March 2026)

| Server | Stars | Category | Tools | Key Pattern |
|---|---|---|---|---|
| Context7 (Upstash) | 44k | Documentation | 2 | Server-side intelligence, behavioral descriptions |
| MindsDB | 30k | Database AI | ~10 | Natural language to SQL |
| GitHub MCP | 20k | Developer tools | ~15 | Workflow-level tools (not raw API) |
| Playwright MCP (Microsoft) | 15k | Browser automation | ~8 | Full browser control |
| PostgreSQL MCP | 1.8k | Database | ~5 | Read/write + performance analysis |
| Google Drive MCP | 2k | Productivity | ~6 | Document search and management |

The pattern across all successful servers: focused scope, minimal tool count, rich descriptions, zero-setup deployment, and server-side processing that minimizes token consumption.
