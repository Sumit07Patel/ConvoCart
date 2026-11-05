import type { Health } from "./App";

const GITHUB = "https://github.com/Sumit07Patel";
const REPO = "https://github.com/Sumit07Patel/ConvoCart";
const LINKEDIN = "https://www.linkedin.com/in/sumit-patel-87565b1b7/";
const PULSEWAVE = "https://pulsewave-ai-support.onrender.com/";

const FLOW = [
  ["Message", "The shopper types in the web chat, in English, Hindi or Hinglish. The session keeps the cart and the last results."],
  ["Understand", "Detects English, Hindi or Hinglish and loads the session: cart, last results, who the shopper is."],
  ["Route", "A LangGraph router sends the turn to the shopping advisor, order support, or a human."],
  ["Act", "The agent calls typed tools: search, cart, discount, order, return. Each agent may use only its own tools."],
  ["Check", "Tools enforce the rules. A reply guard blocks ₹ amounts no tool returned and discounts over the cap."],
];

const RULES = [
  ["Discount cap", "10% at most, and only on carts of ₹999 or more. Asking for 90% gets a polite no."],
  ["Prices from the store", "The model never states a price that no tool returned in this conversation."],
  ["Own orders only", "Another shopper's order id returns “not found”, never details."],
  ["Refunds need a human", "The agent files the request; a person approves it in the Ops tab."],
  ["15-day returns", "Delivered orders only, checked against the delivery date."],
  ["Emails with consent", "One come-back email per cart and per day, only with consent, never a new discount, always an unsubscribe link."],
  ["Reviews are data", "Instructions hidden in review text are ignored."],
  ["Handover", "Complaints, legal threats, claimed authority or a stuck loop go to a person."],
];

const RESULTS = [
  ["9 / 10", "Tool-calling test on Groq openai/gpt-oss-120b: the right tool with valid arguments. Used to pick the model."],
  ["38 / 51", "First run on that live model, before any fixes: 0 guardrail violations and 6 of 6 needed handovers made."],
  ["5 / 6", "The 6 scenarios the free quota blocked, run on the backup model gpt-oss-20b: 0 guardrail violations."],
  ["14 / 14", "All 14 first-run failures after fixing the agent and tests, rerun on the backup model: 0 guardrail violations."],
  ["40 / 40", "Search: a right product in the top 4 on the tuned set (16 English, 14 Hinglish, 10 Hindi)."],
  ["10 / 12", "Search on a held-out set of phrasings the lexicon was not tuned on. Misses: “barsaati”, “pani mein kharab na ho”."],
  ["57 / 57", "Conversation scenarios passed, including 8 attacks, with 0 guardrail violations and every needed handover made (rule-based stand-in model)."],
  ["Fails on purpose", "CI removes a rule (discount or refund) and checks that the scenario gate catches it: 4 and 2 violations."],
  ["130 ms", "95th-percentile app overhead at 20 concurrent users, 0 errors in 1,050 requests (model time excluded)."],
];

const DECISIONS = [
  ["Rules in code, not prompts", "Prompts only remind the model. The discount cap, refund approval and order ownership live in the tools, so a jailbreak cannot talk past them."],
  ["One door to the store", "The agent reaches the store only through a commerce interface, either in-process or over HTTP, the way a real Shopify-style backend would sit behind it."],
  ["Hinglish-aware search", "A small Hindi and Hinglish lexicon turns “barish”, “joote” and “3000 ke andar” into filters before vector search. Loose model categories like “jacket” are mapped to real ones."],
  ["Proving the guardrails", "A deterministic stand-in model lets CI run all 57 scenarios on every push, and a broken-rule job proves the gate fails when a rule is removed."],
  ["Emails driven by store events", "A signed cart.abandoned event triggers the come-back email; order.paid triggers the confirmation. The confirmation is written from the order record, with no model involved."],
  ["Win back without giving away more", "The come-back email may mention only the discount the shopper already bargained for. Any other percentage, price or currency in the model's draft swaps it for a safe template."],
  ["Swap the model with one setting", "One OpenAI-compatible client covers Groq, OpenRouter, Gemini and local Ollama."],
];

const STACK = ["Python", "FastAPI", "LangGraph", "Pydantic", "SQLAlchemy", "Postgres + pgvector", "Groq · gpt-oss-120b",
  "Gmail SMTP", "React + TypeScript", "Vite", "Docker Compose", "GitHub Actions", "Render", "Locust"];

export default function Project({ health }: { health: Health }) {
  return (
    <>
      <footer className="site-foot">
        <div className="wrap foot-row">
          <span>© 2026 Kesar Lane. A demo brand made for a portfolio project, not a real store.<br />
            Photos from Unsplash: Dadee Aissa, Himanshu Dewangan, Equator Stores, Dmytro Shyrokov, Jay Wennington, Chase Charaba.</span>
          <span className="foot-links">
            <a href={REPO} target="_blank" rel="noopener">Source code</a>
            <a href={GITHUB} target="_blank" rel="noopener">GitHub</a>
            <a href={LINKEDIN} target="_blank" rel="noopener">LinkedIn</a>
            <a href="#project">About this project ↓</a>
          </span>
        </div>
      </footer>

      <section id="project" className="project">
        <div className="wrap narrow">
          <p className="muted">Everything above is a demo store. Here is how it works.</p>
          <h2 className="display">ConvoCart</h2>
          <p className="lede">A conversational commerce agent for an Indian D2C brand. It finds products, builds the cart,
            answers order questions, handles returns and wins back left carts by email, in English, Hindi and
            Hinglish, with business rules enforced in code so the model cannot give away what the business would not.</p>
          <div className="cta-row">
            <a href="#assistant" className="btn btn-ink">Try the live agent</a>
            <a href={REPO} target="_blank" rel="noopener" className="btn btn-line">View source on GitHub</a>
            <a href={LINKEDIN} target="_blank" rel="noopener" className="btn btn-line">LinkedIn</a>
          </div>

          <div className="about">
            <div>
              <h3>About me</h3>
              <p>Hi, I am <strong>Sumit Patel</strong>, an embedded systems engineer moving into AI engineering. Embedded
                work taught me that a system is only as good as its failure modes, so this agent is built around
                hard limits, clear handovers and tests that prove the limits hold.</p>
              <p className="muted small">Also by me: <a href={PULSEWAVE} target="_blank" rel="noopener">PulseWave AI Support</a>, a manual-grounded support and RMA assistant.</p>
            </div>
            <div className="cards-2">
              <div className="card-l"><h4>The problem</h4><p>Indian shoppers chat in Hinglish, and a plain LLM bot will happily invent a price, promise 50% off, or read out someone else's order.</p></div>
              <div className="card-l"><h4>The approach</h4><p>Specialist agents that can only act through typed tools, with every money and privacy rule checked by those tools, and a human in the loop for refunds.</p></div>
            </div>
          </div>

          <h3 className="h3">How a message becomes a reply</h3>
          <ol className="flow">
            {FLOW.map(([t, d], i) => <li key={t} className="card-l"><b>{i + 1}. {t}</b><p>{d}</p></li>)}
          </ol>

          <h3 className="h3">Guardrails the model cannot talk past</h3>
          <div className="grid-4">
            {RULES.map(([t, d]) => <div key={t} className="card-l"><h4>{t}</h4><p>{d}</p></div>)}
          </div>
          <p className="muted small">Twelve rules in all, each listed in the repo with where it is enforced and which test proves it.</p>

          <h3 className="h3">Results so far</h3>
          <p className="muted">Measured on simulated data. Each number says what it measured.</p>
          <div className="grid-4">
            {RESULTS.map(([n, d]) => <div key={d} className="card-l stat"><p className="num">{n}</p><p>{d}</p></div>)}
          </div>
          <p className="caveat">What these numbers do not show: the 57 scenarios were scored with a rule-based stand-in
            model, so they prove the rules and plumbing, not the live model's judgement. None of the 14 live failures broke a
            rule, and the fixes include changes to the tests as well as the agent. The fixes have not yet been rerun on the
            main model, because Groq's free tier limits it to about 200,000 tokens a day. The search sets are small and written by me, and the Hindi replies still need
            review by a native speaker. {health?.provider ? `This page is currently using the ${health.provider} model.` : ""}</p>

          <h3 className="h3">Engineering decisions</h3>
          <div className="grid-2">
            {DECISIONS.map(([t, d]) => <div key={t} className="card-l"><h4>{t}</h4><p>{d}</p></div>)}
          </div>

          <h3 className="h3">Tech stack</h3>
          <ul className="stack">{STACK.map((s) => <li key={s}>{s}</li>)}</ul>

          <h3 className="h3">Next improvements</h3>
          <p className="next">Native-speaker review of Hindi replies, a shipping-update email when an order is
            dispatched, and per-visitor rate limits on the chat so the public demo cannot exhaust the free model quota.</p>
        </div>
      </section>
    </>
  );
}
