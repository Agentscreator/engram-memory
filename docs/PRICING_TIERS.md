# Engram Pricing & Usage Tiers

## Free Tier Limits

The free tier is designed for individual developers and small teams to get started with Engram.

| Resource | Free Tier Limit |
|----------|----------------|
| Facts (total) | 1,000 |
| Agents | 3 |
| API requests/month | 10,000 |
| Storage | 100 MB |
| Invite links | 1 |

## Paid Tiers

### Pro ($19/month)
- Facts: 50,000
- Agents: 20
- API requests/month: 100,000
- Storage: 5 GB
- Priority support

### Team ($49/month)
- Facts: 200,000
- Agents: 100
- API requests/month: 500,000
- Storage: 25 GB
- Advanced analytics
- Custom scopes

### Enterprise (Custom pricing)
- Unlimited facts
- Unlimited agents
- Unlimited API calls
- Unlimited storage
- SSO/SAML
- Dedicated support
- SLA guarantee

## In-Product Upgrade Prompts

When users approach their limits, Engram displays contextual upgrade prompts:

### Fact Limit Warning
```
⚠ You've used 900/1,000 facts (90%)
Upgrade to Pro for 50,000 facts → [Upgrade Now]
```

### Agent Limit Warning
```
⚠ You've added 3/3 agents (100%)
Upgrade to Pro for 20 agents → [Upgrade Now]
```

### Rate Limit Warning
```
⚠ Rate limit reached (10,000/month)
Upgrade to Pro for 100k requests/month → [Upgrade Now]
```

## Checking Your Usage

```bash
# Check current usage
engram stats --json

# Check workspace limits
engram config show
```

## Implementation Notes

- Usage is tracked per workspace
- Limits are enforced at the API level
- Upgrade prompts appear in dashboard and CLI
- Hard limits return 429 status with upgrade URL
