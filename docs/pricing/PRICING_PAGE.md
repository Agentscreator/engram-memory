# Pricing Page - engram-memory.com/pricing

## Overview

This document provides the pricing page design for engram-memory.com. Copy the HTML below to your website.

## Pricing Tiers

### Free (Individuals)
- **Price:** $0/month
- **Best for:** Solo developers and experimentation
- **Limits:**
  - 1 workspace
  - 1,000 facts/month
  - 5 agents
  - Local storage only (no team sync)
- **Features:**
  - MCP server (stdio mode)
  - Basic conflict detection
  - SQLite storage
  - Community support

### Team ($15/user/month)
- **Price:** $15/user/month (billed monthly) or $12/user/month (billed annually)
- **Best for:** Engineering teams who need shared memory
- **Limits:**
  - Unlimited workspaces
  - 50,000 facts/user/month
  - Unlimited agents
  - Shared PostgreSQL backend (Engram Cloud hosted)
- **Features:**
  - Everything in Free
  - Team memory sync
  - Dashboard at www.engram-memory.com/dashboard
  - Real-time conflict notifications
  - Invite key-based team joining
  - Priority email support
  - SSO (coming soon)
- **Stripe:** Team tier uses Stripe Checkout for self-service upgrades

### Enterprise (Custom)
- **Price:** Contact us for pricing
- **Best for:** Large organizations with compliance requirements
- **Limits:** Custom based on agreement
- **Features:**
  - Everything in Team
  - SSO (SAML/OIDC)
  - Data residency options (US, EU, APAC)
  - Dedicated SLA (99.9% uptime)
  - Custom rate limits
  - On-premise deployment option
  - Dedicated support engineer
  - Security review & BAA
  - Custom integrations

## Implementation

Copy this HTML for the pricing page:

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
        .pricing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; }
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
        .limits { margin-top: 16px; padding: 12px; background: #f9fafb; border-radius: 8px; font-size: 0.85rem; }
        .limits h4 { margin-bottom: 8px; font-size: 0.9rem; }
        .limits ul { list-style: none; }
        .limits li { padding: 4px 0; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Simple, Transparent Pricing</h1>
        <p class="subtitle">Start free, scale as your team grows</p>
        
        <div class="pricing-grid">
            <!-- Free Tier -->
            <div class="pricing-card">
                <div class="plan-name">Free</div>
                <div class="price">$0<span>/month</span></div>
                <p class="description">Perfect for solo developers and experimentation</p>
                <ul class="features">
                    <li>1 workspace</li>
                    <li>1,000 facts/month</li>
                    <li>5 agents</li>
                    <li>Local storage only</li>
                    <li>MCP server (stdio)</li>
                    <li>Basic conflict detection</li>
                </ul>
                <a href="#" class="cta cta-outline">Get Started</a>
            </div>
            
            <!-- Team Tier -->
            <div class="pricing-card featured">
                <div class="badge">Most Popular</div>
                <div class="plan-name">Team</div>
                <div class="price">$15<span>/user/month</span></div>
                <p class="description">For engineering teams who need shared memory</p>
                <ul class="features">
                    <li>Unlimited workspaces</li>
                    <li>50,000 facts/user/month</li>
                    <li>Unlimited agents</li>
                    <li>Shared PostgreSQL backend</li>
                    <li>Dashboard access</li>
                    <li>Real-time conflict notifications</li>
                    <li>Priority email support</li>
                </ul>
                <a href="#" class="cta cta-primary">Start Free Trial</a>
                <div class="limits">
                    <h4>Or pay annually:</h4>
                    <ul>
                        <li>$12/user/month (save 20%)</li>
                    </ul>
                </div>
            </div>
            
            <!-- Enterprise Tier -->
            <div class="pricing-card">
                <div class="plan-name">Enterprise</div>
                <div class="price">Custom</div>
                <p class="description">For large organizations with compliance requirements</p>
                <ul class="features">
                    <li>Everything in Team</li>
                    <li>SSO (SAML/OIDC)</li>
                    <li>Data residency options</li>
                    <li>Dedicated SLA (99.9%)</li>
                    <li>On-premise option</li>
                    <li>Custom rate limits</li>
                    <li>Dedicated support engineer</li>
                </ul>
                <a href="#" class="cta cta-secondary">Contact Sales</a>
            </div>
        </div>
    </div>
</body>
</html>
```

## Stripe Integration

For Team tier self-service upgrades:

1. Create Stripe products for monthly and annual plans
2. Use Stripe Checkout for payment flow
3. Webhook to update user tier on successful payment

```python
# Example Stripe webhook handler
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig, WEBHOOK_SECRET
        )
    except ValueError:
        return {"error": "Invalid payload"}, 400
    except stripe.error.SignatureVerificationError:
        return {"error": "Invalid signature"}, 400
    
    if event["type"] == "checkout.session.completed":
        # Upgrade user to Team tier
        session = event["data"]["object"]
        user_id = session["metadata"]["user_id"]
        await upgrade_to_team(user_id, session["subscription"])
    
    return {"received": True}
```

## Next Steps

1. Create Stripe account and products
2. Deploy pricing page to engram-memory.com
3. Implement Stripe Checkout flow
4. Set up webhook endpoint
5. Test payment flow end-to-end
