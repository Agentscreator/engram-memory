# OpenAPI 3.1 Specification and Auto-Generated Client SDKs

## Overview

This document describes the OpenAPI specification for Engram's REST API and how to generate client SDKs.

## OpenAPI Specification

The Engram REST API follows OpenAPI 3.1 specification. The spec is available at:

- `/openapi.json` - Generated from code
- `docs/openapi.yaml` - Source specification

### API Endpoints

```yaml
openapi: 3.1.0
info:
  title: Engram API
  version: 1.0.0
  description: Multi-agent memory consistency platform

servers:
  - url: http://localhost:7474
    description: Local development
  - url: https://api.engram.ai
    description: Engram Cloud

paths:
  /api/facts:
    get:
      summary: Query facts
      parameters:
        - name: topic
          in: query
          schema:
            type: string
        - name: scope
          in: query
          schema:
            type: string
        - name: limit
          in: query
          schema:
            type: integer
            default: 10
      responses:
        200:
          description: List of facts
          content:
            application/json:
              schema:
                type: object
                properties:
                  facts:
                    type: array
                    items:
                      $ref: '#/components/schemas/Fact'

  /api/facts:
    post:
      summary: Commit a fact
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/FactInput'
      responses:
        201:
          description: Fact created

components:
  schemas:
    Fact:
      type: object
      properties:
        id:
          type: string
        content:
          type: string
        scope:
          type: string
        confidence:
          type: number
        fact_type:
          type: string

    FactInput:
      type: object
      required:
        - content
        - scope
      properties:
        content:
          type: string
        scope:
          type: string
        confidence:
          type: number
          default: 0.8
        fact_type:
          type: string
          default: observation
```

## Generating SDKs

### Python SDK
```bash
pip install openapi-python-client
openapi-python-client generate --url http://localhost:7474/openapi.json
```

### TypeScript SDK
```bash
npm install @openapi-generator/cli
openapi-generator generate -i http://localhost:7474/openapi.json -g typescript-axios
```

### Go SDK
```bash
go install github.com/go-swagger/go-swagger/cmd/swagger@latest
swagger generate client -f http://localhost:7474/openapi.json
```

## SDK Usage Examples

### Python
```python
from engram_client import EngramClient

client = EngramClient(base_url="http://localhost:7474")
facts = client.facts.get_facts(topic="project context", limit=10)
client.facts.create_fact(content="API updated", scope="backend/api")
```

### TypeScript
```typescript
import { EngramApi } from 'engram-api';

const client = new EngramApi({ basePath: 'http://localhost:7474' });
const facts = await client.getFacts({ topic: 'project context' });
await client.createFact({ content: 'API updated', scope: 'backend' });
```

## Auto-Generation CI

```yaml
# .github/workflows/sdk-generation.yml
name: Generate SDKs

on:
  push:
    paths:
      - 'src/engram/rest.py'
    branches:
      - main

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate Python SDK
        run: |
          pip install openapi-python-client
          openapi-python-client generate --url http://localhost:7474/openapi.json
      - name: Create PR
        run: |
          gh pr create --title "chore: auto-generate Python SDK" --body "Generated from OpenAPI spec"
```

## Versioning

The OpenAPI spec version matches the API version:
- OpenAPI spec 1.0.0 → Engram API 1.0 (stable)
- Breaking changes bump the version (e.g., 2.0.0)

## Documentation

API documentation is available at:
- Swagger UI: `/docs`
- ReDoc: `/redoc`
- Raw spec: `/openapi.json`