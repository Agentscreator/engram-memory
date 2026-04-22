/**
 * EngramToolkit — Engram tools for open-multi-agent ToolRegistry.
 *
 * Registers four tools that agents can call during their runs:
 *   engram_commit    — persist a verified discovery to shared team memory
 *   engram_query     — retrieve what the team knows before starting work
 *   engram_conflicts — surface facts where agents disagree (call before arch decisions)
 *   engram_resolve   — settle a conflict between competing claims
 *
 * Prerequisites: `engram serve --http` running (default http://localhost:7474)
 *
 * Usage:
 *   import { EngramToolkit } from './engram-toolkit.js'
 *   import { ToolRegistry, registerBuiltInTools } from '../../src/index.js'
 *
 *   const registry = new ToolRegistry()
 *   registerBuiltInTools(registry)
 *   new EngramToolkit().registerAll(registry)
 *
 *   // Then pass registry to Agent / OpenMultiAgent as usual.
 *   // Agents see engram_commit, engram_query, engram_conflicts, engram_resolve
 *   // as callable tools and will use them when their system prompts reference Engram.
 */

import { defineTool, ToolRegistry } from '../../src/index.js'
import { z } from 'zod'

export interface EngramToolkitOptions {
  /** Engram server URL. Default: http://localhost:7474 */
  baseUrl?: string
  /** Bearer invite key for authenticated workspaces (ek_live_...). */
  inviteKey?: string
}

export class EngramToolkit {
  private readonly baseUrl: string
  private readonly headers: Record<string, string>

  constructor(options: EngramToolkitOptions = {}) {
    this.baseUrl = (options.baseUrl ?? process.env.ENGRAM_BASE_URL ?? 'http://localhost:7474').replace(/\/$/, '')
    this.headers = { 'Content-Type': 'application/json' }
    const key = options.inviteKey ?? process.env.ENGRAM_INVITE_KEY
    if (key) this.headers['Authorization'] = `Bearer ${key}`
  }

  /** Register all four Engram tools on an existing ToolRegistry. */
  registerAll(registry: ToolRegistry): void {
    for (const tool of this.tools()) registry.register(tool)
  }

  tools() {
    const { baseUrl, headers } = this

    const engramCommit = defineTool({
      name: 'engram_commit',
      description:
        'Persist a verified discovery or decision to shared team memory. ' +
        'Call after you have confirmed a fact — not for speculation. ' +
        'Other agents will see it immediately.',
      inputSchema: z.object({
        content: z.string().describe('The verified fact to store.'),
        scope: z
          .string()
          .describe('Namespace for the fact, e.g. "researcher/findings" or "decisions/arch".'),
        confidence: z
          .number()
          .min(0)
          .max(1)
          .describe('How confident you are (0–1). Use ≥0.8 for well-verified facts.'),
        operation: z
          .enum(['add', 'update', 'delete', 'none'])
          .optional()
          .describe('Memory operation. Use "update" when correcting a prior fact. Default: add.'),
        fact_type: z
          .enum(['observation', 'inference', 'decision'])
          .optional()
          .describe('Category. Default: observation.'),
        agent_id: z.string().optional().describe('Your agent name or ID.'),
        ttl_days: z
          .number()
          .int()
          .positive()
          .optional()
          .describe('Auto-expire after N days. Omit for permanent storage.'),
      }),
      async execute(input) {
        const res = await fetch(`${baseUrl}/api/commit`, {
          method: 'POST',
          headers,
          body: JSON.stringify(input),
        })
        const data = await res.json()
        if (!res.ok) throw new Error((data as { error?: string }).error ?? res.statusText)
        return { data: JSON.stringify(data) }
      },
    })

    const engramQuery = defineTool({
      name: 'engram_query',
      description:
        'Query what your team has already learned. ' +
        'Call BEFORE starting any task to avoid duplicate work and inherit team knowledge.',
      inputSchema: z.object({
        topic: z.string().describe('What you want to know about.'),
        scope: z
          .string()
          .optional()
          .describe('Limit results to a specific scope prefix, e.g. "researcher".'),
        limit: z.number().int().positive().max(50).optional().describe('Max results. Default: 10.'),
        fact_type: z
          .string()
          .optional()
          .describe('Filter by fact type: observation, inference, or decision.'),
      }),
      async execute(input) {
        const res = await fetch(`${baseUrl}/api/query`, {
          method: 'POST',
          headers,
          body: JSON.stringify(input),
        })
        const data = await res.json()
        if (!res.ok) throw new Error((data as { error?: string }).error ?? res.statusText)
        return { data: JSON.stringify(data) }
      },
    })

    const engramConflicts = defineTool({
      name: 'engram_conflicts',
      description:
        'Show how Engram resolved contradictions between agents. ' +
        'Conflicts are resolved automatically — by Claude when ANTHROPIC_API_KEY is set ' +
        '(grounded in codebase truth and belief history), or by confidence/recency heuristic otherwise. ' +
        'Call this to audit resolution decisions before acting on settled facts.',
      inputSchema: z.object({
        scope: z.string().optional().describe('Limit to a scope prefix.'),
        status: z
          .enum(['open', 'resolved', 'dismissed', 'all'])
          .optional()
          .describe('Filter by conflict status. Default: open.'),
      }),
      async execute(input) {
        const params = new URLSearchParams()
        if (input.scope) params.set('scope', input.scope)
        if (input.status) params.set('status', input.status)
        const res = await fetch(`${baseUrl}/api/conflicts?${params}`, { headers })
        const data = await res.json()
        if (!res.ok) throw new Error((data as { error?: string }).error ?? res.statusText)
        return { data: JSON.stringify(data) }
      },
    })

    const engramResolve = defineTool({
      name: 'engram_resolve',
      description:
        'Override an auto-resolution with your own judgement. ' +
        'Engram resolves conflicts automatically, but call this to correct a wrong resolution.',
      inputSchema: z.object({
        conflict_id: z.string().describe('ID of the conflict to resolve.'),
        resolution_type: z
          .enum(['winner', 'merge', 'dismissed'])
          .describe(
            '"winner" picks one claim, "merge" synthesises both, "dismissed" closes without resolution.',
          ),
        resolution: z.string().describe('Explanation of how the conflict was settled.'),
        winning_claim_id: z
          .string()
          .optional()
          .describe('fact_id of the winning claim (required for resolution_type=winner).'),
      }),
      async execute(input) {
        const res = await fetch(`${baseUrl}/api/resolve`, {
          method: 'POST',
          headers,
          body: JSON.stringify(input),
        })
        const data = await res.json()
        if (!res.ok) throw new Error((data as { error?: string }).error ?? res.statusText)
        return { data: JSON.stringify(data) }
      },
    })

    return [engramCommit, engramQuery, engramConflicts, engramResolve]
  }
}
