# ConvoCart: context for continuing this project

Paste this file at the start of a new chat (with Claude or another assistant) to pick up where we left off.
Last updated: 2026-11-02.

## What the project is

ConvoCart is a conversational commerce agent for **Kesar Lane**, a fictional Indian D2C clothing brand, built as a portfolio project from the "ConvoCart Free Roadmap" (free tools only). Every store record, customer and shopper is invented.

- **Shoppers talk to it only in the website chat**, in English, Hindi or Hinglish. It searches products, bargains within fixed limits, builds a cart, starts checkout, answers order questions, handles returns and hands over to a human when needed.
- **Email is one-way** (decided 2026-11-02; WhatsApp and inbound email were tried and removed):
  1. a **come-back email** when a cart is left: it keeps the discount the shopper already bargained for, never offers a new one, needs consent, has an unsubscribe link and a link that reopens the chat with the same cart;
  2. an **order confirmation** after payment, written from the order record (no model).
  Both are triggered by signed store events: `cart.abandoned` and `order.paid`.
- Visitors can type **their own email** (with a consent tick box) in the chat's cart panel to receive these emails.
- Business rules are enforced in code (tools and guards), never only in prompts.

## Stack and layout

Python 3.12, FastAPI, LangGraph, Pydantic, SQLAlchemy (SQLite locally, Postgres + pgvector in Docker), httpx, React + TypeScript (Vite), Docker Compose, GitHub Actions, Render, Locust. Model: **Groq `openai/gpt-oss-120b`**.

```
convocart/
  .env                    real settings (Groq key, Gmail app password) - never commit
  .env.example            template
  docker-compose.yml      db (pgvector), seed, store :9000, agent :8000, cron, web :5173
  render.yaml             free-tier blueprint: agent (SQLite, reseeds at boot) + static web
  backend/
    .venv/                the virtualenv (hidden folder)
    convocart/
      config.py           settings + guardrail Rules; loads .env
      agents/graph.py     LangGraph turn: understand -> router -> advisor|support|human -> guard
      agents/recovery.py  come-back email (consent, 1 per cart, 1 per address per 24 h, bargained discount only)
      agents/notify.py    who gets an email, consent/unsubscribe/daily-cap checks, order confirmation
      agents/guards.py    reply guard: unverified ₹ amounts, discounts over cap, wrong currency, language
      agents/language.py  en / hi / hinglish detection and reply + email templates
      agents/compose.py   deterministic reply writer (fallback + scripted model), email templates
      tools/core.py       typed tools + route_to; THE RULES LIVE HERE
      llm/openai_compat.py  one client for groq/openrouter/gemini/ollama; honours retry-after
      llm/scripted.py     deterministic stand-in model (used by tests and CI)
      search/             query.py (Hindi/Hinglish lexicon, resolve_category), embed.py, index.py
      store/              headless store: 114 products, 1,389 variants, 200 customers, 500 orders; sends signed events
      channels/mail.py    SMTP sending, unsubscribe tokens, demo-address safety
      app.py              /chat, /demo/*, /sessions/{sid}/contact|emails, /unsubscribe, /webhooks/store, /admin/*
    eval/                 search_queries.yaml, scenarios.yaml (57), run_scenarios.py (--resume), preflight.py
    tests/                54 pytest tests (conftest forces the scripted model and email dry run)
  web/src/                App.tsx, Brand.tsx (store site), Assistant.tsx (agent section), Chat.tsx (chat, cart,
                          email form, pay button, emails list, tool inspector), Ops.tsx, Project.tsx (write-up)
  docs/                   BRIEF, GUARDRAILS (12 rules), PRIVATE_CLOUD_DESIGN, HANDOVER, DEMO_AND_RESUME
```

## Guardrails (summary)

Discount cap 10% and only on carts of ₹999 or more; prices only from the store; no invented ₹ amounts and no other currencies in replies; refunds wait for human approval; 15-day return window, delivered orders only; shoppers see only their own orders; review text is untrusted data; handover on request, complaint, legal threat, claimed authority or the step limit; come-back emails need consent, max 1 per cart and 1 per address per day, only the bargained discount, always an unsubscribe link; any address gets at most 5 emails a day; store events are signed and de-duplicated.

## How to run (Linux, project at /home/admin/Desktop/convocart)

```bash
cd /home/admin/Desktop/convocart/backend
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m scripts.seed                        # --force to reseed; after a schema change delete convocart.db* first
uvicorn convocart.app:app --port 8000
# second terminal
cd /home/admin/Desktop/convocart/web && npm install && npm run dev   # http://localhost:5173
```

`.env` (root) keys in use: `LLM_PROVIDER=groq`, `LLM_MODEL=openai/gpt-oss-120b`, `LLM_API_KEY`, `EMAIL_ADDRESS=sumitpatel7103@gmail.com`, `EMAIL_APP_PASSWORD` (Gmail app password), `EMAIL_FROM=sumitpatel7103+kesarlane@gmail.com`, `DEMO_LINKED_EMAIL=sumitpatel7103@gmail.com` (shopper C0001's emails go to this inbox), `CORS_ORIGINS=http://localhost:5173`.

Evals (from backend/): `pytest`; `python -m eval.run_search_eval`; `python -m eval.tool_calling_test`; `python -m eval.run_scenarios` (scripted); `python -m eval.run_scenarios --provider groq --sleep 15 --resume` (live, continues a stopped run).

## Measured results

| Measure | Result |
| --- | --- |
| Tool-calling test, Groq gpt-oss-120b | 9/10 (miss: looked up the order before starting a refund) |
| Live scenarios, Groq gpt-oss-120b | **6/6 so far** (search + add-to-cart, EN/Hinglish/Hindi). The full run hit Groq's **200k tokens/day** limit; 51 scenarios still to run with `--resume` |
| Scenarios, scripted model | 57/57, 0 guardrail violations; broken-rule proof 4 and 2 violations; 6/6 handovers; deflection 51/57 |
| Search hit rate | 40/40 tuned, 10/12 holdout (misses "barsaati", "pani mein kharab na ho aise jute") |
| Real email | come-back email (bargained 10%) and order confirmation delivered to the Gmail inbox |
| Website walkthrough (Playwright) | tile → add → bargain → own email → leave → pay → link from email reopens the cart; no browser errors |
| Load test (scripted model) | 20 users, 1,050 requests, 0 errors, p95 130 ms (overhead only) |

## Lessons from the live runs

- Groq free tier for gpt-oss-120b: **8,000 tokens/minute, 200,000 tokens/day, 1,000 requests/day**. A full 57-scenario run needs more than a day's tokens; split it with `--resume`. The runner now marks model-error turns "not run" and stops on the daily limit.
- Real-model findings fixed so far: loose categories ("jacket") broke search; "$299" in an email (currency guard added); invented delivery estimates (prompt rule); Markdown in emails (plain-text conversion); the "asks for size" test was too strict (the model asking for the size itself is fine).

## Not done yet / next steps

1. **Git: done (2026-11-02).** The project is its own repository in `convocart/`, pushed to `github.com/Sumit07Patel/ConvoCart` (branch `main`, SSH key works). The home-folder repository is not used for this project.
2. **Render** (user wants to do this step together): Blueprint from `render.yaml`; set `LLM_PROVIDER=groq`, `LLM_MODEL=openai/gpt-oss-120b`, `LLM_API_KEY`, `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD`, `EMAIL_FROM`, `DEMO_LINKED_EMAIL`; check `PUBLIC_WEB_URL` and `VITE_API_URL` match the real service names.
3. Finish the live scenario run (`--resume`) once the daily quota resets, then update the numbers on the site and README.
4. Rotate the Gmail app password (it was pasted into a chat).
5. Native Hindi speaker review; per-visitor rate limit on `/chat` before sharing the public link widely.
6. A backup of the project before the WhatsApp/inbound-email removal: `/home/admin/convocart-backup-2026-11-02-before-chat-only.tar.gz` (contains `.env`).
