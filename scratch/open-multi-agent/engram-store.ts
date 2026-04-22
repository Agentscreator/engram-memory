/**
 * EngramMemoryStore — persistent MemoryStore for open-multi-agent.
 *
 * Drop-in replacement for InMemoryStore backed by an Engram server, giving
 * your agents durable shared memory that survives process restarts and flags
 * conflicts when agents disagree.
 *
 * Prerequisites: `engram serve --http` running (default http://localhost:7474)
 *
 * Usage:
 *   import { EngramMemoryStore } from './engram-store.js'
 *
 *   const store = new EngramMemoryStore()
 *   // Use directly as a MemoryStore in Agent or tool context
 *   const entry = await store.get('researcher/findings')
 */

import type { MemoryEntry, MemoryStore } from '../../src/index.js'

export interface EngramStoreOptions {
  /** Engram server URL. Default: http://localhost:7474 */
  baseUrl?: string
  /** Bearer invite key for authenticated workspaces (ek_live_...). */
  inviteKey?: string
  /** Confidence score attached to every committed fact. Default: 0.9 */
  confidence?: number
}

export class EngramMemoryStore implements MemoryStore {
  private readonly baseUrl: string
  private readonly headers: Record<string, string>
  private readonly confidence: number

  constructor(options: EngramStoreOptions = {}) {
    this.baseUrl = (options.baseUrl ?? process.env.ENGRAM_BASE_URL ?? 'http://localhost:7474').replace(/\/$/, '')
    this.confidence = options.confidence ?? 0.9
    this.headers = { 'Content-Type': 'application/json' }
    const key = options.inviteKey ?? process.env.ENGRAM_INVITE_KEY
    if (key) this.headers['Authorization'] = `Bearer ${key}`
  }

  async set(key: string, value: string, metadata?: Record<string, unknown>): Promise<void> {
    const agentId = typeof metadata?.agent === 'string' ? metadata.agent : undefined
    await this._post('/api/commit', {
      content: value,
      scope: key,
      confidence: this.confidence,
      agent_id: agentId,
      operation: 'update',
    })
  }

  async get(key: string): Promise<MemoryEntry | null> {
    const data = await this._get(`/api/facts?scope=${encodeURIComponent(key)}&limit=1`)
    const facts = toFactArray(data)
    if (facts.length === 0) return null
    return toMemoryEntry(key, facts[0])
  }

  async list(): Promise<MemoryEntry[]> {
    const data = await this._get('/api/facts?limit=200')
    return toFactArray(data).map((f) => toMemoryEntry(f.scope ?? f.fact_id, f))
  }

  async delete(key: string): Promise<void> {
    await this._post('/api/commit', {
      content: '__deleted__',
      scope: key,
      confidence: 1.0,
      operation: 'delete',
    })
  }

  // Engram preserves all facts for audit — bulk clear is intentionally a no-op.
  async clear(): Promise<void> {}

  // ── HTTP helpers ────────────────────────────────────────────────────────────

  private async _post(path: string, body: unknown): Promise<unknown> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = (await res.json().catch(() => ({}))) as { error?: string }
      throw new Error(`Engram POST ${path} ${res.status}: ${err.error ?? res.statusText}`)
    }
    return res.json()
  }

  private async _get(path: string): Promise<unknown> {
    const res = await fetch(`${this.baseUrl}${path}`, { headers: this.headers })
    if (!res.ok) {
      const err = (await res.json().catch(() => ({}))) as { error?: string }
      throw new Error(`Engram GET ${path} ${res.status}: ${err.error ?? res.statusText}`)
    }
    return res.json()
  }
}

// ── Internal helpers ──────────────────────────────────────────────────────────

interface EngramFact {
  fact_id: string
  content: string
  scope?: string
  agent_id?: string
  committed_at: string
}

function toFactArray(data: unknown): EngramFact[] {
  if (Array.isArray(data)) return data as EngramFact[]
  if (data && typeof data === 'object' && 'facts' in data) {
    return (data as { facts: EngramFact[] }).facts
  }
  return []
}

function toMemoryEntry(key: string, fact: EngramFact): MemoryEntry {
  return {
    key,
    value: fact.content,
    metadata: { agent: fact.agent_id, factId: fact.fact_id },
    createdAt: new Date(fact.committed_at),
  }
}
