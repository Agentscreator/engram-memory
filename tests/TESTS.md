# Test Suite

Run all tests with:

```bash
uv run pytest tests/ -x
```

Run a specific file:

```bash
uv run pytest tests/test_memory_lifecycle.py -v
```

All tests are async (`pytest-asyncio`, `asyncio_mode = "auto"`). Fixtures in `conftest.py` provide a fresh SQLite database and engine instance per test via `tmp_path` — no persistent state, no network calls.

---

## Test Modules

### `test_memory_lifecycle.py` — Ephemeral memory lifecycle

Validates that the memory durability system behaves as documented: ephemeral facts expire, reinforcement promotes them, explicit promotion is permanent, and durable facts are never swept.

Time is controlled by passing a synthetic `as_of` timestamp to `expire_ttl_facts()` — no wall-clock sleeps.

| Test | What it checks |
| --- | --- |
| `test_ephemeral_fact_is_immediately_retrievable` | An ephemeral fact committed via the engine is accessible in storage immediately after commit, with `valid_until` set to a future date (engine applies 1-day default TTL) |
| `test_ephemeral_fact_expires_after_ttl_sweep` | A directly-inserted ephemeral fact with an elapsed TTL has its `valid_until` set when `expire_ttl_facts` runs past the expiry date |
| `test_reinforcement_marks_fact_as_promotable` | After two `increment_query_hits` calls, a no-TTL ephemeral fact appears in `get_promotable_ephemeral_facts` |
| `test_reinforcement_auto_promote_prevents_expiry` | An ephemeral fact that is promoted after reaching the query-hit threshold is not swept by the TTL worker (`expire_ttl_facts` returns 0) |
| `test_explicit_promotion_clears_ttl` | `engine.promote()` sets `durability='durable'`, clears `valid_until`, and clears `ttl_days` — making the fact permanently active |
| `test_explicit_promotion_overrides_ttl_sweep` | A directly-inserted ephemeral fact that is promoted via `storage.promote_fact()` is skipped by `expire_ttl_facts` |
| `test_durable_fact_survives_ttl_sweep` | A durable fact with no TTL is untouched by `expire_ttl_facts` even when `as_of` is set 365 days in the future |
| `test_corroborated_fact_survives_ttl_sweep` | A durable, corroborated fact (with provenance) is unaffected by the TTL sweep far in the future |

---

### `test_conflicts.py` — Conflict detection and resolution

Validates that contradictory facts are surfaced as conflicts, that severity classification is consistent, and that the resolution path correctly settles disagreements.

| Test | What it checks |
| --- | --- |
| `test_direct_numeric_contradiction_raises_conflict` | Two facts with contradictory numeric rate-limit values in the same scope produce at least one open conflict via `tier0_entity` or `tier2_numeric` |
| `test_same_entity_different_value_produces_conflict` | Two facts with the same config entity name but different values produce a conflict; accepted tiers are `tier0_entity`, `tier2_numeric`, or `tier1_nli` depending on entity extraction |
| `test_conflict_classification_is_high_severity_for_cross_agent` | A numeric conflict between two different engineers is classified as `high` severity |
| `test_winner_resolution_closes_losing_fact` | Resolving a conflict with `"winner"` closes the losing fact (`valid_until` set) while the winning fact remains active (`valid_until` is None); conflict status moves to `"resolved"` |
| `test_dismissed_resolution_leaves_both_facts_active` | Resolving a conflict as `"dismissed"` records a false-positive and leaves both facts with `valid_until = None` |

---

## Other Test Modules

| File | Coverage area |
| --- | --- |
| `test_engine.py` | Core commit pipeline, dedup, secret scanning, operation types, query ranking, numeric/semantic conflict detection, corroboration, lineage, batch commit, export |
| `test_storage.py` | SQLite CRUD, fact dedup, conflict lifecycle, agent upsert, TTL expiry, stale retirement, workspace stats, timelines, promotion helpers |
| `test_auth.py` | Workspace init, invite key creation/validation/consumption, key rotation |
| `test_rest.py` | REST API endpoints: `/api/commit`, `/api/query`, `/api/conflicts`, `/api/resolve`, `/api/stats` |
| `test_dashboard.py` | Dashboard HTML rendering and HTMX partial responses |
| `test_entities.py` | Entity extraction pipeline (numeric, version, config_key, technology types) |
| `test_secrets.py` | Secret scanning: API keys, tokens, connection strings, false-positive avoidance |
| `test_export.py` | JSON and Markdown snapshot export |
| `test_federation.py` | Replication journal: fact ingestion, dedup across workspaces |
| `test_workspace.py` | Workspace config read/write, anonymous mode, multi-tenancy |
| `test_workspace_isolation.py` | Facts and conflicts from one workspace are invisible to another |
| `test_cli_config.py` | `engram config` subcommands |
| `test_cli_install.py` | `engram install` IDE config injection |
| `test_cli_search.py` | `engram search` CLI command |
| `test_cli_tail.py` | `engram tail` live-tail command |
| `test_verify.py` | `engram verify` / `engram doctor` schema, connectivity, MCP, and NLI checks |
| `test_install_sh.py` | Shell installer script correctness |
| `test_rediscovery_experiment.py` | Rediscovery / re-embedding experiment harness |
