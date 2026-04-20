# Official TypeScript/JavaScript SDK

This document specifies the official TypeScript/JavaScript SDK for Engram.

## Overview

| Package | NPM | Status |
|---------|-----|--------|
| @engram/sdk | planned | v0.1.0 |

## Installation

```bash
npm install @engram/sdk
# or
yarn add @engram/sdk
```

## Quick Start

```typescript
import { EngramClient } from '@engram/sdk';

const client = new EngramClient({
  workspace: 'ek_live_...',  // Invite key
});

// Commit a fact
const fact = await client.commit({
  content: 'Rate limit is 1000 req/s',
  scope: 'config/api',
  confidence: 0.95,
});

// Query facts
const results = await client.query('rate limit config');

// Get conflicts
const conflicts = await client.getConflicts();

// Resolve a conflict
await client.resolve({
  conflictId: 'conflict-abc123',
  resolution: 'keep_a',
});
```

## API Reference

### Constructor

```typescript
new EngramClient(options: EngramClientOptions);
```

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| workspace | string | Yes | Invite key or workspace ID |
| apiUrl | string | No | MCP server URL (default: 'https://mcp.engram.app/mcp') |
| apiKey | string | No | API key for hosted mode |
| timeout | number | No | Request timeout in ms (default: 30000) |

### Methods

#### commit()

```typescript
const fact = await client.commit(options: CommitOptions);
```

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| content | string | Yes | The fact content |
| scope | string | No | Scope (default: 'default') |
| confidence | number | No | Confidence 0-1 (default: 0.5) |
| factType | string | No | 'observation', 'inference', 'decision' |
| ttlDays | number | No | Days until expiry (default: 30) |

Returns: `Promise<CommitResult>`

```typescript
interface CommitResult {
  id: string;
  content: string;
  scope: string;
  committedAt: string;
  lineageId: string;
}
```

#### query()

```typescript
const results = await client.query(query: string, options?: QueryOptions);
```

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| query | string | Yes | Search query |
| scope | string | No | Filter by scope |
| limit | number | No | Max results (default: 20) |
| asOf | string | No | Historical timestamp |

Returns: `Promise<Fact[]>`

```typescript
interface Fact {
  id: string;
  content: string;
  scope: string;
  agentId: string;
  confidence: number;
  committedAt: string;
  validFrom: string;
  validUntil: string | null;
}
```

#### getConflicts()

```typescript
const conflicts = await client.getConflicts(options?: ConflictOptions);
```

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| scope | string | No | Filter by scope |
| status | string | No | 'open', 'resolved' |
| limit | number | No | Max results (default: 20) |

Returns: `Promise<Conflict[]>`

#### resolve()

```typescript
await client.resolve(options: ResolveOptions);
```

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| conflictId | string | Yes | Conflict ID |
| resolution | string | Yes | 'keep_a', 'keep_b', 'both_valid', 'merge' |
| note | string | No | Resolution note |
| mergedContent | string | No | For 'merge' resolution |

#### getStatus()

```typescript
const status = await client.getStatus();
```

Returns: `Promise<WorkspaceStatus>`

```typescript
interface WorkspaceStatus {
  workspaceId: string;
  displayName: string;
  factCount: number;
  conflictCount: number;
  createdAt: string;
}
```

## Error Handling

```typescript
try {
  const fact = await client.commit({ content: 'Test' });
} catch (error) {
  if (error instanceof EngramError) {
    console.error(error.code, error.message);
  }
}
```

| Error Code | Description |
|-----------|-------------|
| WORKSPACE_NOT_FOUND | Invalid invite key |
| RATE_LIMIT_EXCEEDED | Too many requests |
| CONFLICT_DETECTED | Fact contradicts existing fact |

## TypeScript Support

The SDK is written in TypeScript with full type definitions:

```typescript
import type { Fact, Conflict, WorkspaceStatus } from '@engram/sdk';
```

## Browser Support

```html
<script type="module">
  import { EngramClient } from 'https://cdn.engram.app/sdk/v0.1.0/engram-sdk.js';
  
  const client = new EngramClient({ workspace: 'ek_live_...' });
</script>
```

## Examples

### Next.js Integration

```typescript
// app/api/engram/route.ts
import { EngramClient } from '@engram/sdk';
import { NextRequest } from 'next/server';

export async function POST(request: NextRequest) {
  const client = new EngramClient({
    workspace: process.env.ENGRAM_WORKSPACE!,
  });
  
  const body = await request.json();
  const result = await client.query(body.query);
  
  return Response.json(result);
}
```

### Express.js Integration

```typescript
import express from 'express';
import { EngramClient } from '@engram/sdk';

const app = express();
const client = new EngramClient({
  workspace: process.env.ENGRAM_WORKSPACE!,
});

app.post('/query', async (req, res) => {
  const results = await client.query(req.body.query);
  res.json(results);
});
```

### React Hook

```typescript
import { useEngram } from '@engram/sdk/react';

function MyComponent() {
  const { query, commit, loading } = useEngram({
    workspace: 'ek_live_...',
  });
  
  const handleSearch = async () => {
    const results = await query('rate limit');
  };
  
  return <button onClick={handleSearch}>Search</button>;
}
```

## Roadmap

| Version | Feature |
|---------|---------|
| 0.1.0 | Core commit/query/resolve |
| 0.2.0 | Conflict detection hooks |
| 0.3.0 | React integration |
| 0.4.0 | Streaming queries |
| 1.0.0 | Stable release |

## Related Documentation

- [IMPLEMENTATION.md](./IMPLEMENTATION.md)
- [MCP_TOOL_AUDIT.md](./MCP_TOOL_AUDIT.md)