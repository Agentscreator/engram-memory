# Engram Integration for n8n and Zapier/Make

This document describes the API endpoints for creating n8n nodes and Zapier/Make webhooks.

## REST API Endpoints

### Query Facts
```
GET /api/query?topic=<search_term>
```

**Headers:**
```
Authorization: Bearer <invite_key>
```

**Response:**
```json
{
  "facts": [
    {
      "id": "abc123",
      "content": "The API timeout is 30 seconds",
      "scope": "api-config",
      "agent_id": "agent-1",
      "confidence": 0.9,
      "created_at": "2026-04-19T12:00:00Z"
    }
  ],
  "token使用时": "query"
}
```

### Commit Fact
```
POST /api/commit
```

**Headers:**
```
Authorization: Bearer <invite_key>
Content-Type: application/json
```

**Body:**
```json
{
  "content": "The API timeout is 30 seconds",
  "scope": "api-config",
  "confidence": 0.9,
  "agent_id": "agent-1"
}
```

**Response:**
```json
{
  "fact_id": "abc123",
  "workspace_id": "ws_123"
}
```

### Get Conflicts
```
GET /api/conflicts?status=open
```

**Headers:**
```
Authorization: Bearer <invite_key>
```

**Response:**
```json
[
  {
    "conflict_id": "conf_123",
    "explanation": "Numeric contradiction: timeout=30 vs timeout=60",
    "severity": "high",
    "status": "open",
    "fact_a": {
      "content": "The API timeout is 30 seconds",
      "scope": "api-config"
    },
    "fact_b": {
      "content": "The API timeout is 60 seconds",
      "scope": "api-config"
    }
  }
]
```

### Resolve Conflict
```
POST /api/conflicts/<conflict_id>/resolve
```

**Headers:**
```
Authorization: Bearer <invite_key>
Content-Type: application/json
```

**Body:**
```json
{
  "resolution_type": "winner",
  "resolution": "Confirmed: timeout is 30 seconds per ops runbook",
  "winning_claim_id": "abc123"
}
```

**Response:**
```json
{
  "resolved": true
}
```

### Get Workspace Stats
```
GET /api/stats
```

**Headers:**
```
Authorization: Bearer <invite_key>
```

**Response:**
```json
{
  "facts": {
    "total": 150,
    "by_durability": {
      "durable": 120,
      "ephemeral": 30
    }
  },
  "conflicts": {
    "open": 3,
    "resolved": 12,
    "total": 15
  },
  "agents": {
    "active": 8
  }
}
```

## n8n Node Configuration

### HTTP Request Node Settings

For n8n, use the HTTP Request node with:

- **Method:** POST (for commit) or GET (for query)
- **URL:** `https://engram.example.com/api/query`
- **Authentication:** Bearer Auth
- **Header:** `Authorization: Bearer your_invite_key`

### Example n8n Workflow

1. **Trigger:** Slack message or Webhook
2. **HTTP Request:** Call Engram API
3. **IF:** Response has facts → Send to Slack
4. **ELSE:** Return "No facts found"

## Zapier/Make Webhook Configuration

### Make.com Scenario

1. **Trigger:** Webhook
2. **HTTP Request:** Call Engram API with auth header
3. **Filter:** Check if response has facts
4. **Return:** Formatted response

### Environment Variables

Set in Zapier/Make:
- `ENGRAM_API_URL` - Your Engram server URL
- `ENGRAM_INVITE_KEY` - Your workspace invite key

## Example Usage

### Search for API Config
```
GET /api/query?topic=api+timeout
```

### Commit a Discovery
```
POST /api/commit
{"content": "API timeout is 30 seconds", "scope": "api-config"}
```

### Check for Conflicts
```
GET /api/conflicts?status=open
```

## Rate Limits

- 100 requests/minute per workspace
- Contact support for higher limits