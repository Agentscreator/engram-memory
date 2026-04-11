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
| Alqithami [6] (FiFA/MaRS) | Memory-budgeted forgetting policies | Importance-based decay | No (single-agent) | 2025 |
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
| Playwright MCP (Microsoft) | 15k | Browser automation | ~8 | Accessibility snapshots, not screenshots |
| PostgreSQL MCP | 1.8k | Database | ~5 | Read/write + performance analysis |
| Google Drive MCP | 2k | Productivity | ~6 | Document search and management |

The pattern across all successful servers: focused scope, minimal tool count, rich descriptions, zero-setup deployment, and server-side processing that minimizes token consumption.

---

## Platform-Level MCP Implementations

### Microsoft — Azure MCP Server + Enterprise Security Architecture

**Sources:** [Azure SDK Blog](https://devblogs.microsoft.com/azure-sdk/introducing-the-azure-mcp-server/) (May 2025), [OWASP MCP Top 10 for Azure](https://microsoft.github.io/mcp-azure-security-guide/), [Azure DevOps Remote MCP](https://github.com/microsoft/azure-devops-mcp)

Microsoft's MCP strategy operates at two levels:

1. **Product-level servers:** Azure MCP Server (Cosmos DB, Storage, Monitor, App Config, Resource Groups, Azure CLI, azd). Playwright MCP (15k stars). Azure DevOps Remote MCP. All open-source.

2. **Enterprise architecture guidance:** The OWASP MCP Top 10 security guide defines the deployment pattern that Engram should follow for team/enterprise use:
   - Stdio for prototyping only. Remote HTTP for production.
   - Remote servers behind Azure API Management gateway.
   - Microsoft Entra ID for authentication (no static API keys).
   - Centralized policy enforcement (rate limiting, DLP, access control).
   - Comprehensive monitoring via Application Insights and Log Analytics.
   - Key stat from Astrix Security: 88% of MCP servers require credentials, 53% rely on long-lived static secrets — making stdio inappropriate for enterprise.

**Impact on Engram:** Engram's three-tier auth model (local/team/enterprise) mirrors Microsoft's stdio→HTTP progression. The enterprise tier should support API gateway integration and identity provider federation.

### Google — Managed Remote MCP for Cloud Databases

**Sources:** [Google Cloud Blog](https://cloud.google.com/blog/products/databases/managed-mcp-servers-for-google-cloud-databases) (Feb 2026), [MCP Toolbox for Databases](https://cloud.google.com/blog/products/ai-machine-learning/mcp-toolbox-for-databases-now-supports-model-context-protocol)

Google's approach is the most ambitious: fully managed, zero-infrastructure MCP servers for AlloyDB, Spanner, Cloud SQL, Firestore, Bigtable, BigQuery, and Google Maps. Key design decisions:

- **Zero infrastructure deployment:** Configure the MCP server endpoint in agent config. No server to deploy, no database to manage. Enterprise-grade auditing, observability, and governance included.
- **Identity-first security:** Authentication via IAM, not shared keys. Agents can only access tables/views explicitly authorized by the user.
- **Full audit trail:** Every query and action logged in Cloud Audit Logs. Security teams get a record of every database interaction.
- **Developer Knowledge MCP server:** Connects IDEs to Google's documentation — the same pattern as Context7 but for Google's own docs.

**Impact on Engram:** Google's managed model is the aspirational end state for Engram's team deployment. The path: local stdio → self-hosted HTTP → (future) managed cloud endpoint. Google's IAM-based auth and audit logging patterns should inform Engram's enterprise tier.

### Apple — OS-Level MCP Integration

**Source:** [9to5Mac](https://9to5mac.com/2025/09/22/macos-tahoe-26-1-beta-1-mcp-integration/) (Sep 2025)

Apple is integrating MCP support at the OS level via the App Intents framework in macOS Tahoe 26.1, iOS 26.1, and iPadOS 26.1. This means:

- Developers can expose app actions to any MCP-compatible AI agent through system-level integration.
- ChatGPT, Claude, or any MCP-friendly model could interact directly with Mac, iPhone, and iPad apps.
- Developers don't need to implement MCP themselves — the OS provides the bridge.

**Impact on Engram:** MCP is becoming an OS-level primitive. This validates the bet on MCP as the protocol layer. When Apple ships MCP support, Engram will be accessible from any MCP-compatible agent on macOS/iOS without additional integration work.

### Linux Foundation — Agentic AI Foundation (AAIF)

**Sources:** [Linux Foundation announcement](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation) (Dec 2025), [Anthropic blog](https://www.anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation)

The AAIF brings three complementary building blocks under neutral governance:

| Project | Donated by | Purpose |
|---|---|---|
| MCP | Anthropic | Connectivity — how agents talk to tools and data |
| goose | Block | Execution runtime — reference agent framework |
| AGENTS.md | OpenAI | Repository guidance — project-specific context for agents |

Platinum members: AWS, Anthropic, Block, Bloomberg, Cloudflare, Google, Microsoft, OpenAI. Gold: Cisco, Datadog, IBM, Oracle, Salesforce, SAP, Shopify, Snowflake.

**Impact on Engram:** Engram sits at the intersection of all three AAIF projects. It is an MCP server (connectivity). It should work seamlessly with goose (execution). It should be referenced in AGENTS.md files (guidance). This three-way integration is the distribution strategy.

### OpenAI — AGENTS.md Standard

**Sources:** [AGENTS.md spec](https://agents.md), [Stackademic analysis](https://blog.stackademic.com/agents-md-the-readme-your-ai-coding-agent-actually-reads-e634b7e2de34) (Jun 2026)

AGENTS.md is a plain Markdown file at the repository root that gives AI coding agents project-specific context: build instructions, coding conventions, testing policies, security rules. 20k+ repos adopted. Supported by OpenAI Codex, Cursor, Google Jules, Amp, Factory.

**Impact on Engram:** Engram ships a reference AGENTS.md template that tells agents when to query shared memory, when to commit facts, how to interpret conflicts, and what scopes to use. This is zero-cost distribution — a template in the docs that users drop into their repos.

## [5] MemFactory: Unified Inference & Training Framework for Agent Memory

**Authors:** Ziliang Guo, Ziheng Li, Bo Tang, Feiyu Xiong, Zhiyu Li
**Affiliations:** MemTensor
**Venue:** arXiv preprint, April 1, 2026
**ArXiv:** [2603.29493](https://arxiv.org/abs/2603.29493)
**File:** [`papers/2603.29493v2.pdf`](papers/2603.29493v2.pdf)

### Summary

MemFactory is a modular framework for memory-augmented LLM agents. It decomposes the memory lifecycle into four layers — *Module*, *Agent*, *Environment*, and *Trainer* — and applies GRPO (Group Relative Policy Optimization) to fine-tune memory management policies. The Module Layer defines three atomic operations: **Extractor** (parse raw context into structured memories), **Updater** (assign ADD/UPDATE/DEL/NONE to each candidate), and **Retriever** (fetch relevant memories, with an optional LRM-based reranker). Empirically validates 14.8% gains over baselines on the MemAgent benchmark.

### Key Concepts

- **CRUD memory operations (Memory-R1 pattern):** Each incoming memory is explicitly assigned one of ADD, UPDATE, DEL, or NONE. This makes agent intent explicit and prevents silent accumulation of stale facts.
- **Semantic auto-updater:** When an agent signals UPDATE without specifying what to supersede, the system compares the new content against existing memories via embedding similarity and automatically closes the best match above a threshold — no manual lineage tracking required.
- **RerankRetriever:** Post-retrieval reranking with a Large Reasoning Model to improve precision. Engram already uses RRF fusion (embedding + FTS5); this identifies a future extension point.
- **GRPO training layer:** Trains the agent's memory policy using multi-dimensional reward signals (format compliance, LLM-as-a-judge). Not directly applicable to Engram's server-side architecture.

### Impact on Engram

The CRUD operations pattern was directly implemented:

1. **`operation` parameter on `engram_commit`** — agents now pass `"add"` (default), `"update"`, `"delete"`, or `"none"` to make their intent explicit.
2. **Semantic auto-updater** — `operation="update"` without `corrects_lineage` triggers an embedding search across active facts in scope; the best match above 0.75 cosine similarity is automatically superseded.
3. **`memory_op` + `supersedes_fact_id` columns** — stored per fact for a complete audit trail of memory lifecycle operations.
4. **`operation="delete"`** — retires an entire lineage without inserting a replacement fact.
5. **`operation="none"`** — explicit no-op that signals the agent has nothing new to add (useful in multi-agent pipelines where a tool call is required by protocol but the agent has already retrieved enough context).

---

## [6] Forgetful but Faithful: A Cognitive Memory Architecture and Benchmark for Privacy-Aware Generative Agents (FiFA/MaRS)

**Authors:** Saad Alqithami
**ArXiv:** [2512.12856](https://arxiv.org/abs/2512.12856) (v1, Dec 2025)
**File:** [`papers/2512.12856v1.pdf`](papers/2512.12856v1.pdf)

### Summary

FiFA introduces the Memory-Aware Retention Schema (MaRS), a cognitively inspired architecture that organizes episodic, semantic, social, and task memories as typed, provenance-tracked nodes with multiple indices. On top of MaRS, six forgetting policies are formalized: FIFO, LRU, Priority Decay, Reflection-Summary, Random-Drop, and a Hybrid variant. The FiFA benchmark evaluates agents across narrative coherence, goal completion, social recall, privacy preservation, and cost efficiency under explicit token budgets.

### Key Findings for Engram

1. **Principled forgetting improves coherence.** The central finding: agents that forget strategically outperform agents that remember everything. Random Drop achieved the highest composite score (0.911) and narrative coherence (0.667), partly because non-deterministic eviction avoids reinforcing stale, self-contradictory fragments. This validates the "proved useful more than once" heuristic — keeping less but keeping the right things.

2. **Importance-based decay is the right lever at scale.** Priority Decay and Hybrid policies improve goal completion and coherence over temporal baselines by protecting high-value items (decisions, verified facts, corroborated claims) while aggressively pruning low-value noise (old inferences, unverified observations). The density score `score(n) = (Û_n - λ_priv * s_n) / w_n` directly inspired Engram's enhanced scoring formula.

3. **Budget independence over tested range.** Policy choice dominates outcomes more than raw capacity. Increasing memory budget from 2K to 32K tokens improved scores modestly but did not change policy rankings. This means Engram's retrieval quality depends more on what it keeps than how much it stores.

4. **Unverified inferences are the primary source of noise.** Facts without provenance and without corroboration are the most likely to introduce "weird assumptions" that degrade agent performance. The paper's sensitivity analysis shows these should decay fastest.

5. **Typed memory with differential decay rates.** Different fact types warrant different retention policies: decisions have high retention value (architectural choices persist), observations have moderate value (raw sightings decay), and inferences have the lowest retention value (conclusions without evidence should expire).

### Impact on Engram (Round 8)

FiFA's insights directly shaped three changes to Engram's retrieval and retention:

1. **Steeper recency decay** — `exp(-0.1 * days)` replaces `exp(-0.05 * days)`. Half-life drops from ~14 days to ~7 days. A 90-day-old fact is now effectively invisible in scoring (0.001 vs 0.011). This prevents old context from crowding out recent, relevant facts at 100k+ scale.

2. **Importance-based background decay** — A new periodic task (`_decay_loop`) retires stale, low-value facts: unverified inferences after 30 days, unverified uncorroborated observations after 90 days. Decisions and facts with provenance or corroboration are protected. This is FiFA's Priority Decay policy adapted to Engram's temporal validity model.

3. **Aggressive penalty for unverified old inferences** — In query scoring, inferences older than 14 days without provenance get a 0.3× multiplier. These are the "weird assumptions" that the FiFA paper identifies as the primary source of agent performance degradation.

---

### MCP Registry — Official Discovery

**Source:** [MCP Registry](https://modelcontextprotocol.io/registry), [MCP Blog](https://blog.modelcontextprotocol.io/posts/2025-09-08-mcp-registry-preview/)

The official MCP Registry is a centralized metadata repository for publicly accessible MCP servers, backed by Anthropic, GitHub, PulseMCP, and Microsoft. It standardizes how servers are distributed and discovered.

**Impact on Engram:** Engram should be listed in the official MCP Registry from day one. This is the primary discovery channel for MCP servers. The registry entry should clearly position Engram as the consistency layer — the one thing no other listed server does.

---

## [7] Differential Privacy for Vector-Based Fact Stores (Issue #76 Survey)

**Topic:** Survey of differential privacy (DP) techniques applicable to a vector-based fact store

### Why This Matters

Engram's privacy model is "we don't read your data." But what about inference attacks from conflict detection output — can a malicious team member learn sensitive facts from the timing or content of conflict signals? This survey evaluates DP techniques to close this gap.

### Key Techniques Evaluated

| Technique | Description | Privacy Budget Cost | Conflict Detection Accuracy Loss |
|-----------|-------------|---------------------|-----------------------------------|
| DP Embeddings (Gaussian Mechanism) | Add calibrated noise to embeddings before storage | ε ≈ 1.0-2.0 | 5-15% similarity score degradation |
| Local DP (Randomized Response) | Perturb committed facts before embedding | ε ≈ 0.5-1.0 | 10-20% false positive increase |
| DP in Similarity Scores | Calibrate noise injection at query time | ε ≈ 0.1-0.5 | Minimal for large corpora, 5-10% for small |
| Membership Inference Defenses | Aggregate query patterns to detect probing | N/A (defense) | Slight query latency overhead |
| Secure Aggregation | Aggregate conflict signals without exposing individual facts | ε ≈ 0.01-0.1 | Requires threshold-based output |

### Tradeoff Analysis

**Low Privacy Budget (ε = 0.1):**
- Use case: Enterprise compliance (HIPAA, GDPR)
- Embedding utility: 70-80% preserved
- Conflict detection: Tier 0 (entity/numeric) unaffected, Tier 1 (NLI) degrades ~10%
- Recommendation: Apply DP only to embeddings, not to metadata

**Medium Privacy Budget (ε = 1.0):**
- Use case: Standard team deployment
- Embedding utility: 85-90% preserved
- Conflict detection: Tier 0 unaffected, Tier 1 degrades ~5%
- Recommendation: DP embeddings + noise on conflict similarity scores

**High Privacy Budget (ε = 10+):**
- Use case: Research/development
- Embedding utility: 95%+ preserved
- Conflict detection: Minimal impact
- Recommendation: No DP needed — baseline is sufficient

### Relevance to Engram

Engram's threat model is **curious but non-adversarial team members** — not external attackers. This significantly reduces the attack surface:

1. **Inference from conflict timing:** A team member already has access to their own commits. Conflict signals reveal what others committed, but this is the intended function. DP would add complexity without meaningful privacy gain.

2. **Membership inference:** Determining if a specific fact exists in the store. With 100k+ facts, this is already difficult. For sensitive use cases, the team can enable `anonymous_mode`.

3. **Recommendation:** Do not implement DP at this stage. The current privacy model (client-side encryption, anonymous mode) addresses the primary concerns. DP adds significant implementation complexity (noise calibration, privacy budget management) for marginal benefit in the permissioned team setting.

**Future work:** If enterprise customers request DP, the implementation path is:
1. Add noise at embedding generation time (client-side)
2. Calibrate ε based on workspace size
3. Update conflict detection to handle noisy embeddings

