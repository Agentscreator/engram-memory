/**
 * Engram + open-multi-agent: Persistent Research Team
 *
 * A three-agent team (researcher, fact-checker, writer) that shares verified
 * knowledge via Engram. Facts survive process restarts. When two agents reach
 * contradictory conclusions, Engram flags the conflict automatically.
 *
 * Prerequisites:
 *   - Engram server: `engram serve --http`  (default http://localhost:7474)
 *   - API key env var for your chosen provider (see table below)
 *
 * Run with Anthropic (default):
 *   ANTHROPIC_API_KEY=sk-ant-... npx tsx examples/integrations/with-engram/research-team.ts
 *
 * Run with OpenAI:
 *   AGENT_PROVIDER=openai AGENT_MODEL=gpt-4o OPENAI_API_KEY=sk-... npx tsx examples/integrations/with-engram/research-team.ts
 *
 * Run with Gemini:
 *   AGENT_PROVIDER=gemini AGENT_MODEL=gemini-2.5-pro GEMINI_API_KEY=... npx tsx examples/integrations/with-engram/research-team.ts
 *
 * Run with Grok:
 *   AGENT_PROVIDER=grok AGENT_MODEL=grok-3 XAI_API_KEY=... npx tsx examples/integrations/with-engram/research-team.ts
 *
 * Run with GitHub Copilot (interactive OAuth2 if no token set):
 *   AGENT_PROVIDER=copilot AGENT_MODEL=gpt-4o npx tsx examples/integrations/with-engram/research-team.ts
 *
 * Run with DeepSeek:
 *   AGENT_PROVIDER=deepseek AGENT_MODEL=deepseek-chat DEEPSEEK_API_KEY=... npx tsx examples/integrations/with-engram/research-team.ts
 *
 * Run with MiniMax:
 *   AGENT_PROVIDER=minimax AGENT_MODEL=abab6.5s-chat MINIMAX_API_KEY=... npx tsx examples/integrations/with-engram/research-team.ts
 *
 * Run with Azure OpenAI:
 *   AGENT_PROVIDER=azure-openai AGENT_MODEL=gpt-4o AZURE_OPENAI_API_KEY=... AZURE_OPENAI_ENDPOINT=https://....openai.azure.com npx tsx examples/integrations/with-engram/research-team.ts
 */

import { Agent, AgentConfig, ToolExecutor, ToolRegistry, registerBuiltInTools } from '../../src/index.js'
import type { SupportedProvider } from '../../src/llm/adapter.js'
import { EngramToolkit } from './engram-toolkit.js'

// ── Provider configuration ────────────────────────────────────────────────────

/** Narrower union that AgentConfig.provider accepts. */
type AgentProvider = AgentConfig['provider']

/** Required env var per provider. `null` = provider has its own auth flow. */
const PROVIDER_API_KEYS: Record<SupportedProvider, string | null> = {
  anthropic:    'ANTHROPIC_API_KEY',
  openai:       'OPENAI_API_KEY',
  gemini:       'GEMINI_API_KEY',
  grok:         'XAI_API_KEY',
  copilot:      null,                // uses GITHUB_COPILOT_TOKEN / GITHUB_TOKEN or interactive OAuth2
  deepseek:     'DEEPSEEK_API_KEY',
  minimax:      'MINIMAX_API_KEY',
  'azure-openai': 'AZURE_OPENAI_API_KEY',
}

/** Sensible default model per provider. */
const DEFAULT_MODELS: Record<SupportedProvider, string> = {
  anthropic:    'claude-opus-4-7',
  openai:       'gpt-4o',
  gemini:       'gemini-2.5-pro',
  grok:         'grok-3',
  copilot:      'gpt-4o',
  deepseek:     'deepseek-chat',
  minimax:      'abab6.5s-chat',
  'azure-openai': 'gpt-4o',
}

function resolveProvider(): { provider: AgentProvider; model: string } {
  const rawProvider = (process.env.AGENT_PROVIDER ?? 'anthropic') as SupportedProvider

  if (!(rawProvider in PROVIDER_API_KEYS)) {
    const supported = Object.keys(PROVIDER_API_KEYS).join(', ')
    throw new Error(`Unknown provider "${rawProvider}". Supported: ${supported}`)
  }

  const requiredKey = PROVIDER_API_KEYS[rawProvider]
  if (requiredKey && !process.env[requiredKey]) {
    throw new Error(
      `Provider "${rawProvider}" requires ${requiredKey} to be set.\n` +
      `  export ${requiredKey}=<your-key>`,
    )
  }

  const model = process.env.AGENT_MODEL ?? DEFAULT_MODELS[rawProvider]

  // AgentConfig.provider is a narrower union than SupportedProvider.
  // Providers outside that union (deepseek, minimax, azure-openai) are passed
  // through as undefined and the framework resolves them via createAdapter defaults.
  const agentProvider = rawProvider as AgentProvider

  return { provider: agentProvider, model }
}

const { provider, model } = resolveProvider()

// ── Shared setup ──────────────────────────────────────────────────────────────

const TOPIC = 'the current state of AI agent memory systems'

const registry = new ToolRegistry()
registerBuiltInTools(registry)

new EngramToolkit().registerAll(registry)

const executor = new ToolExecutor(registry)

const ENGRAM_TOOLS = ['engram_commit', 'engram_query', 'engram_conflicts', 'engram_resolve']

// ── Agents ────────────────────────────────────────────────────────────────────

const researcher = new Agent(
  {
    name: 'researcher',
    provider,
    model,
    tools: ENGRAM_TOOLS,
    systemPrompt: `You are a research agent. Your job is to gather key facts about a topic.

Before starting:
1. Call engram_query to check what the team already knows — skip facts already covered.

While researching:
- Call engram_commit to record each verified finding (scope: "research/findings", confidence ≥ 0.8).
- Use fact_type "observation" for facts, "inference" for conclusions you've drawn.
- Be precise: commit one discrete fact per call, not a wall of text.

After researching:
- Call engram_query to confirm your findings are saved.`,
  },
  registry,
  executor,
)

const factChecker = new Agent(
  {
    name: 'fact-checker',
    provider,
    model,
    tools: ENGRAM_TOOLS,
    systemPrompt: `You are a fact-checking agent. Your job is to verify and sharpen what the research agent found.

Steps:
1. Call engram_query with topic "${TOPIC}" to retrieve the researcher's findings.
2. For each finding, assess its accuracy and completeness.
3. If you find a correction or a more precise version, call engram_commit with
   operation "update" and confidence ≥ the original. Engram will automatically
   resolve any contradiction — by Claude if ANTHROPIC_API_KEY is set, otherwise
   by confidence/recency heuristic.
4. Call engram_conflicts to review how any contradictions were resolved and confirm
   the resolution looks correct. You do not need to resolve them yourself.`,
  },
  registry,
  executor,
)

const writer = new Agent(
  {
    name: 'writer',
    provider,
    model,
    tools: ENGRAM_TOOLS,
    systemPrompt: `You are a technical writer. Your job is to produce a polished briefing.

Steps:
1. Call engram_query with topic "${TOPIC}" to get the team's settled knowledge.
   Engram has already auto-resolved any contradictions between agents — the facts
   you receive represent the team's current agreed understanding.
2. Optionally call engram_conflicts to see what was disputed and how it was resolved —
   this gives useful context for nuance in the briefing.
3. Write a concise 3–5 paragraph briefing grounded only in what Engram contains.
   Do not invent facts.`,
  },
  registry,
  executor,
)

// ── Run ───────────────────────────────────────────────────────────────────────

console.log(`Provider: ${provider ?? 'default'}  Model: ${model}\n`)

console.log(`── Researcher ──────────────────────────────────────────`)
const researchResult = await researcher.run(
  `Research the key facts about ${TOPIC}. Commit your findings to Engram.`,
)
console.log(researchResult.output)

console.log(`\n── Fact-checker ────────────────────────────────────────`)
const checkResult = await factChecker.run(
  `Fact-check the research findings in Engram about ${TOPIC}. Correct anything inaccurate.`,
)
console.log(checkResult.output)

console.log(`\n── Writer ──────────────────────────────────────────────`)
const writeResult = await writer.run(
  `Write a briefing on ${TOPIC} using only what the team verified in Engram.`,
)
console.log(writeResult.output)

console.log(`\n── Done ────────────────────────────────────────────────`)
console.log('Facts are persisted in Engram. Re-run the writer alone to regenerate the briefing.')
console.log('Open http://localhost:7474/dashboard to browse the team memory.')
