# Pricing Page - engram-memory.com/pricing

## Overview

This document provides the pricing page design for engram-memory.com.

## Pricing Tiers

All plans include LLM suggestions, conflict detection, and the full feature set. Plans differ only by monthly commit volume.

### Free
- **Price:** $0/month
- **Best for:** Solo developers and experimentation
- **Commits:** 500/month
- **Features:**
  - MCP server (stdio + HTTP)
  - Conflict detection (entity, NLI, narrative coherence)
  - LLM suggestions for conflict resolution
  - Forgetting-based memory management
  - Dashboard access
  - 1 workspace

### Builder ($12/month)
- **Price:** $12/month
- **Best for:** Solo developers shipping regularly
- **Commits:** 5,000/month
- **Features:**
  - Everything in Free
  - Overage at $0.015/commit above limit
  - Unlimited workspaces

### Team ($39/month)
- **Price:** $39/month
- **Best for:** Engineering teams with shared memory
- **Commits:** 25,000/month
- **Features:**
  - Everything in Builder
  - Invite key-based team joining
  - Priority email support

### Scale ($99/month)
- **Price:** $99/month
- **Best for:** Production workloads at scale
- **Commits:** 100,000/month
- **Features:**
  - Everything in Team
  - Dedicated support
  - Custom rate limits

## Implementation

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pricing - Engram</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 1200px; margin: 0 auto; padding: 40px 20px; }
        h1 { text-align: center; font-size: 2.5rem; margin-bottom: 16px; }
        .subtitle { text-align: center; color: #666; margin-bottom: 48px; font-size: 1.1rem; }
        .pricing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 24px; }
        .pricing-card { background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 32px; position: relative; transition: transform 0.2s, box-shadow 0.2s; }
        .pricing-card:hover { transform: translateY(-4px); box-shadow: 0 12px 24px rgba(0,0,0,0.1); }
        .pricing-card.featured { border: 2px solid #6366f1; }
        .badge { position: absolute; top: -12px; left: 50%; transform: translateX(-50%); background: #6366f1; color: white; padding: 4px 16px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
        .plan-name { font-size: 1.25rem; font-weight: 600; margin-bottom: 8px; }
        .price { font-size: 2.5rem; font-weight: 700; margin-bottom: 8px; }
        .price span { font-size: 1rem; font-weight: 400; color: #666; }
        .description { color: #666; margin-bottom: 24px; font-size: 0.9rem; }
        .features { list-style: none; margin-bottom: 24px; }
        .features li { padding: 8px 0; border-bottom: 1px solid #f3f4f6; display: flex; align-items: center; gap: 8px; }
        .features li::before { content: "✓"; color: #10b981; font-weight: bold; }
        .cta { display: block; width: 100%; padding: 12px; text-align: center; border-radius: 8px; text-decoration: none; font-weight: 600; transition: background 0.2s; }
        .cta-primary { background: #6366f1; color: white; }
        .cta-primary:hover { background: #4f46e5; }
        .cta-secondary { background: #f3f4f6; color: #374151; }
        .cta-secondary:hover { background: #e5e7eb; }
        .cta-outline { border: 1px solid #d1d5db; color: #374151; }
        .cta-outline:hover { background: #f9fafb; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Simple, Transparent Pricing</h1>
        <p class="subtitle">All plans include LLM suggestions and conflict detection. Scale by commits.</p>

        <div class="pricing-grid">
            <div class="pricing-card">
                <div class="plan-name">Free</div>
                <div class="price">$0<span>/month</span></div>
                <p class="description">Solo developers and experimentation</p>
                <ul class="features">
                    <li>500 commits/month</li>
                    <li>LLM suggestions</li>
                    <li>Conflict detection</li>
                    <li>Forgetting-based memory</li>
                    <li>Dashboard access</li>
                </ul>
                <a href="#" class="cta cta-outline">Get Started</a>
            </div>

            <div class="pricing-card">
                <div class="plan-name">Builder</div>
                <div class="price">$12<span>/month</span></div>
                <p class="description">Solo developers shipping regularly</p>
                <ul class="features">
                    <li>5,000 commits/month</li>
                    <li>Everything in Free</li>
                    <li>Overage at $0.015/commit</li>
                    <li>Unlimited workspaces</li>
                </ul>
                <a href="#" class="cta cta-primary">Upgrade</a>
            </div>

            <div class="pricing-card featured">
                <div class="badge">Most Popular</div>
                <div class="plan-name">Team</div>
                <div class="price">$39<span>/month</span></div>
                <p class="description">Engineering teams with shared memory</p>
                <ul class="features">
                    <li>25,000 commits/month</li>
                    <li>Everything in Builder</li>
                    <li>Team invite keys</li>
                    <li>Priority support</li>
                </ul>
                <a href="#" class="cta cta-primary">Upgrade</a>
            </div>

            <div class="pricing-card">
                <div class="plan-name">Scale</div>
                <div class="price">$99<span>/month</span></div>
                <p class="description">Production workloads at scale</p>
                <ul class="features">
                    <li>100,000 commits/month</li>
                    <li>Everything in Team</li>
                    <li>Dedicated support</li>
                    <li>Custom rate limits</li>
                </ul>
                <a href="#" class="cta cta-secondary">Upgrade</a>
            </div>
        </div>
    </div>
</body>
</html>
```

## Stripe Integration

Stripe handles subscriptions for Builder, Team, and Scale tiers. Free tier requires no payment.

Overage on paid plans is billed at $0.015/commit above the monthly limit via Stripe metered billing at period end.
