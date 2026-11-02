# Client brief: Kesar Lane × ConvoCart

*Phase 1 deliverable. Kesar Lane is a fictional brand; every product, customer and order in this project is invented.*

## The brand

Kesar Lane is a direct-to-consumer clothing and accessories brand selling online across India: monsoon wear (rain jackets, waterproof footwear, umbrellas), everyday and festive ethnic wear (kurtas, kurtis, sarees, dupattas), basics, bags and small accessories. About 114 products, prices from ₹199 to ₹8,999. Most orders arrive from mobile, and a large share of pre-purchase questions come in on WhatsApp, often in Hinglish.

## Customers

- **Metro shoppers, 22-40**, comfortable in English, often switching to Hinglish on WhatsApp.
- **Tier-2 and tier-3 shoppers** who prefer Hindi (Devanagari) or Hinglish and expect a reply in the same language.
- **Repeat buyers** asking where an order is, or how to return or exchange a size.

## The three problems

1. **Support load.** The team answers the same questions all day: "where is my order", "how do I return this", "do you have this in M". Replies slow down in the monsoon and festive peaks.
2. **Lost carts.** Shoppers build a cart and leave. There is no follow-up today, and the team doesn't want spammy blasts.
3. **Discovery in the shopper's own words.** Site search fails on "monsoon ke liye halki jacket 3000 ke andar". Shoppers give up or ask on WhatsApp.

## What we will build

A conversational agent in the website chat with three specialists behind a router: a shopping advisor (search, compare, bargain within limits, cart, checkout), an order-support agent (status, returns, exchanges, refunds with human approval) and a win-back agent that sends one consented come-back email for a left cart. Every paid order gets a confirmation email. Business rules stay in code, not in prompts.

## How we will measure success

| Goal | Measure | Target for the pilot |
| --- | --- | --- |
| Find the right product | Search hit rate: expected product in the top 4; Hinglish and Hindi reported separately | ≥ 90% on the test set; holdout reported as is |
| Resolve without a human | Deflection rate on simulated conversations | Report it; no target until real traffic |
| Hand over when needed | Cases that needed a human and got one; cases wrongly handed over | 100% / 0 |
| Never break a rule | Guardrail violations: discounts above cap, invented prices, other customers' data, refunds without approval, messages without consent | **0**, enforced in CI |
| Fast enough for chat | Median and 95th-percentile turn latency | Report per model; under 5 s p95 with a hosted model |

Results from simulated shoppers are simulation results, not business results.
