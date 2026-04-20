# The Narrative Coherence Detective

> This document describes the conflict detection mechanism used in the **hosted
> Engram service** (`api/mcp.py`). The local server (`src/engram/engine.py`) uses
> the tiered NLI pipeline described in `docs/IMPLEMENTATION.md` § Phase 3.

---

## The Core Idea

The hosted conflict detector is not a classifier. It does not compare pairs of facts
and ask "do these contradict?" It reads the workspace's entire commit history as a
**story** — oldest fact first — and asks a different question:

> *If a new agent joined this project today and read these facts top to bottom,
> where would they get confused about what's currently true?*

This framing shift matters. Pairwise contradiction detection misses the most common
real-world failure mode: not two facts that directly contradict, but a **reversal** —
the story says "we use X", then "we switched to Y", then "we use X again." No single
pair contradicts. The whole arc is incoherent.

The detective catches reversals, ambiguity, and stale claims that pairwise detection
cannot see.

---

## What the Detective Looks For

Three categories of confusion:

**Reversals** — The story changes direction and then changes back. An agent reading
chronologically would not know which state is current.

> *"We use REST" → "We switched to GraphQL" → "The API is REST-based"*

**Ambiguity** — Two currently active facts say different things about the same subject.
An agent would have to guess which to follow.

> *"The rate limit is 1,000 req/s"* (scope: `auth`) alongside *"Auth allows 5,000
> req/s per IP"* (scope: `infra`) — both active, both plausible, neither retired.

**Stale claims** — An old fact is clearly outdated given newer context but was never
explicitly retired. The agent would act on wrong information.

> *"Postgres 14 is our database version"* committed 8 months ago, never superseded,
> while recent facts discuss Postgres 17 migration work.

---

## What the Detective Ignores

Equally important is what it does **not** flag:

- **Natural progression** — "We did X, then improved to Y" is normal development.
  The detective does not flag evolution, only incoherence.
- **Design iteration and mind-changes** — When someone corrects or refines an earlier
  decision, the later fact *is* the current truth. The earlier fact is just history.
  This is how architecture solidifies. The arc "we thought X → actually it's Y" is
  resolved, not ambiguous. The detective reads the most recent relevant fact as
  settling the question.
- **Facts about different subjects** — Even if two facts use similar words, if they
  describe different things, there is no confusion.
- **Facts from the same conversation** — Facts committed minutes apart in the same
  scope, evolving together, are not flagged. That is a working session, not a conflict.
- **Cases where chronological order makes the current state clear** — If the story
  unambiguously resolves to a current state, no flag is raised.

The key test the detective applies: does the *most recent* relevant fact leave the
question open, or does it settle it? If it settles it, no flag. Only when the latest
state of the story is genuinely unclear — two equally current-looking facts pointing
in different directions — does the detective intervene.

The goal is a low false-positive rate. A new agent reading the facts should be able
to act on them. The detective only intervenes when that agent would genuinely not know
what to do.

---

## The Forgetting Curve

A workspace accumulates hundreds or thousands of facts over time. Sending all of them
to an LLM on every commit would be expensive, slow, and noisy — recent churn drowns
out the signal.

The detective applies a **probabilistic forgetting curve** before building the story,
inspired by the FiFA (Forgetting in Fact Archives) approach:

| Fact age | Survival rate |
|---|---|
| < 24 hours | 20–40% (high churn, low signal) |
| 1–7 days | 10–20% |
| > 7 days | 5–10% |

This is not random deletion. It is **weighted sampling** — older facts are more likely
to be forgotten, but the sample is drawn probabilistically so important old facts
occasionally survive.

**Conflict history overrides forgetting.** Facts that have previously been involved in
a detected conflict survive at 2× the base rate per conflict flag. These are the facts
that have already proven contentious — the detective needs to keep seeing them.

**The trigger fact always survives.** The newly committed fact that triggered the
detection run is always included in the story, regardless of the forgetting curve.

The result: the detective reads a curated, representative sample of the workspace's
history — not a firehose, not a random subset, but a signal-weighted narrative.

---

## The Prompt

The detective is given the surviving facts in chronological order (oldest first) and
asked to read them as a story:

```
You are a detective reading the chronological story of a software project's
shared memory. Each line is a fact committed by an AI agent, with timestamp
and scope.

Read the story and identify points where an agent joining this project TODAY
would get confused. You're looking for:

• REVERSALS — the story says 'we use X', then later 'we switched to Y',
  then even later 'we use X' again. Which is it now?
• AMBIGUITY — two facts that are both currently active say different things
  about the same subject. An agent wouldn't know which to follow.
• STALE CLAIMS — an old fact is clearly outdated based on newer context
  but was never explicitly retired.

DO NOT FLAG:
• Natural progression (we did X, then improved to Y) — that's normal
• Design iteration and mind-changes — when someone corrects or refines an
  earlier decision, the later fact IS the current truth. The earlier fact
  is just history. The arc 'we thought X → actually it's Y' is resolved.
• Facts about different subjects, even if they use similar words
• Facts from the same conversation (minutes apart, same scope) evolving
• Anything where the chronological order makes the current state clear —
  if the most recent fact settles the question, there is no confusion

The key test: does the MOST RECENT relevant fact leave the question open,
or does it settle it? If it settles it, do not flag.

For each confusion you find, return:
- "fact_ids": array of the 8-char IDs of the facts involved
- "question": a 1-2 sentence yes/no question a human can answer to
  clarify. Frame as: 'Is [specific thing] still the case?'

Respond with ONLY a JSON array. If the story is coherent, respond with: []
```

The output is a JSON array of `{fact_ids, question}` objects. Each question is
written so a human can answer it without reading the raw facts — it names the
specific thing in dispute.

---

## Batching

When the surviving fact set exceeds ~6,000 tokens (~24,000 characters), it is split
into overlapping batches. Each batch is checked independently and the results are
merged. Batches preserve chronological order — the detective always reads the story
in sequence, never out of order.

---

## Deduplication

Before inserting a detected conflict, the detective checks whether the same pair of
facts has already been flagged:

```sql
SELECT 1 FROM conflicts
WHERE workspace_id = $1
  AND ((fact_a_id = $2 AND fact_b_id = $3)
    OR (fact_a_id = $3 AND fact_b_id = $2))
```

If the pair already exists (open or resolved), it is skipped. This prevents the same
confusion from generating duplicate conflict cards on every new commit.

---

## Model

The detective uses `gpt-4o-mini` with `temperature=0`. The low temperature is
intentional — the detective is making a factual judgment about the story, not
generating creative output. Determinism matters more than diversity here.

The system prompt frames the detective's role explicitly:

> *"You are a narrative coherence detective for a team's shared AI memory. Read the
> chronological story and identify where a new agent would get confused about the
> current state of things. Normal development progression is not confusion. Only flag
> genuine ambiguity that would cause an agent to act on wrong information."*

---

## Async Execution

Detection runs **after** the commit returns. The committing agent never waits for the
detective. The flow is:

```
engram_commit() called
    │
    ├── Insert fact into database  ← synchronous, <10ms
    │
    └── Return {fact_id, committed_at, ...}  ← agent continues immediately

    [background]
    _detect_conflicts() called with new fact_id
        │
        ├── Fetch all active facts (chronological)
        ├── Apply forgetting curve
        ├── Build story batches
        ├── Call gpt-4o-mini for each batch (parallel)
        ├── Parse JSON results
        └── Insert new conflicts into database
```

If `OPENAI_API_KEY` is not set, the detective is silently disabled. The commit
pipeline continues to work; conflict detection simply does not run.

---

## Relationship to the Tiered Pipeline

The local server (`src/engram/engine.py`) uses a different approach: a four-tier
deterministic + ML pipeline (entity exact-match → NLI cross-encoder → numeric rules
→ LLM escalation). That pipeline is optimized for CPU-first local deployment with no
external API dependencies.

The hosted detective trades the deterministic tiers for a single narrative pass. The
tradeoff:

| | Tiered pipeline (local) | Narrative detective (hosted) |
|---|---|---|
| External API required | No | Yes (OpenAI) |
| Catches numeric conflicts | Yes (Tier 0, deterministic) | Sometimes (LLM judgment) |
| Catches reversals | Partially (pairwise only) | Yes (reads full story arc) |
| Catches stale claims | No | Yes |
| False positive rate | Low (deterministic tiers anchor it) | Low (conservative prompt) |
| Latency | 2–5s background | 3–8s background |
| Cost | Free (local models) | ~$0.001–0.005 per commit |

Neither approach is strictly better. The tiered pipeline has higher precision on
numeric/structural conflicts. The narrative detective has broader coverage of
story-level incoherence. A future version may combine both.

---

## Where to Find the Code

- **Hosted detective:** `api/mcp.py` → `_detect_conflicts()`
- **Forgetting curve:** `src/engram/forgetting.py` → `apply_forgetting()`
- **Tiered pipeline (local):** `src/engram/engine.py` → `_run_conflict_detection()`
- **Dashboard conflict UI:** `api/dashboard_page.py` → `renderConflicts()`
- **Local dashboard conflict cards:** `src/engram/dashboard.py` → `_render_conflict_card()`
