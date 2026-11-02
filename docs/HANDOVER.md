# Handover note: ConvoCart for Kesar Lane

*One page, written as if for the client. All data is invented and all shoppers are simulated.*

## What was delivered

- **Agents:** a router and three specialists (shopping advisor, order support, cart recovery) in LangGraph, with session memory, human handover and a step limit. English, Hindi and Hinglish, replying in the shopper's language.
- **Typed tools with the rules inside:** 11 Pydantic-validated tools plus a routing tool; discount cap, store-only prices, own-orders-only, return window and refund approval are enforced in code (see GUARDRAILS.md).
- **Channels:** React + TypeScript web chat is the only conversation channel. Email is one-way: a come-back email for a left cart (consent, unsubscribe link, the bargained discount only) and an order confirmation, both triggered by signed store events (`cart.abandoned`, `order.paid`) and sent over SMTP (Gmail app password). WhatsApp and inbound email were tried and removed.
- **Store:** a headless store service with its own API (114 products, 1,389 variants with stock, 200 customers, 500 orders) kept separate from the agent layer.
- **Model wrapper:** one switch (`LLM_PROVIDER`) for Groq, OpenRouter, Gemini or a local Ollama model; a scripted stand-in model for free, repeatable CI.
- **Quality:** 36 automated tests, a 52-query search eval, a 55-scenario eval with attack cases, a CI gate that fails on any guardrail violation, traces of every step and tool call, Docker Compose, a Render blueprint and a Locust load test.

## Measured results

| Measure | Result | Conditions |
| --- | --- | --- |
| Search hit rate (top 4) | 40/40 (100%): English 16/16, Hinglish 14/14, Hindi 10/10 | Test set written while building the language rules, so optimistic |
| Search hit rate, holdout | 10/12 (83%): English 5/5, Hindi 3/3, **Hinglish 2/4** | Written after the rules were frozen; misses left in |
| Scenario task success | 57/57 | **Scripted model.** Shows the pipeline and rules work, not model quality |
| Guardrail violations | **0** | Same 57 scenarios incl. 8 attacks. With a rule deliberately broken: 4 (discount) and 2 (refund), gate fails |
| Handover | 6/6 needed handovers made, 0 wrong | Scripted model |
| Deflection (simulated) | 49/55 conversations (89%) without a human | Mix of scenarios chosen by us, not real traffic |
| Turn latency | p50 21 ms, p95 35 ms (eval); p50 48 ms, p95 130 ms at 20 concurrent users, 0 errors in 1,050 requests | Scripted model, SQLite; orchestration overhead only |
| Cart recovery | Flow works end to end (reminder → reply → checkout → paid) in 1 of 1 opted-in returning-shopper script | Scripted shopper; not a recovery rate |
| Cost | ₹0 | Free tools only; no cost per conversation is claimed |

## Known limits

- **The live model has only partly been evaluated.** Groq `openai/gpt-oss-120b` scored 9/10 on the tool-calling test and 6/6 on the first live scenarios; the full run stopped at the free tier's 200k tokens/day. Finish it with `python -m eval.run_scenarios --provider groq --sleep 15 --resume` before quoting a live task-success rate.
- Hindi and Hinglish reply templates and the language rules have **not been reviewed by a native speaker**.
- Search uses hashed word and character n-grams plus a hand-written Hindi/Hinglish lexicon, not a semantic model; the holdout set shows it misses unfamiliar Hinglish words ("barsaati", "pani mein kharab na ho"). FastEmbed is wired in as an option but was not evaluated.
- The abandoned-cart scan runs on demand (the demo's *Leave for 2 h*) or from the cron service; on Render's free tier there is no cron, so real come-back emails go out only from the demo button.
- Emails are plain text from a personal Gmail; a real shop would use a sending domain with SPF/DKIM.
- The pgvector search path and the Docker Compose stack were written but not run in the build environment (no Docker daemon or pgvector available there); the first CI run exercises pgvector. The rest of the test suite was also run against a real Postgres 16.
- The demo identity picker stands in for login. There is no real authentication on the web chat.

## What comes next

1. Run `eval.tool_calling_test` and `eval.run_scenarios --provider ollama`, then a hosted free model spread over several days; publish both tables with failures.
2. Native-speaker review of 30 Hindi and Hinglish replies; fix and re-run.
3. Record a demo where the come-back email and order confirmation arrive in a real inbox.
4. Try `EMBEDDER=fastembed` and compare the holdout hit rate.
5. Pilot with real (consented) traffic before claiming any deflection or recovery rate.
