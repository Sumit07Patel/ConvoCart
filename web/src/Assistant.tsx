import { useEffect, useState } from "react";
import { api, type Customer } from "./api";
import type { Health } from "./App";
import Chat from "./Chat";
import Ops from "./Ops";

type Tab = "web" | "ops";

const LANG_LABEL: Record<string, string> = { en: "English", hinglish: "Hinglish", hi: "हिंदी" };

// What the agent does for the business, step by step through a shopper's journey.
const JOURNEY = [
  { step: "Discover", what: "Searches 114 products from plain requests like “barish wale joote, 2000 tak”." },
  { step: "Cart", what: "Adds “the second one in M”, checks stock and size before it says yes." },
  { step: "Bargain", what: "Gives a discount only within the 10% cap, and only on carts of ₹999 or more." },
  { step: "Support", what: "Tracks orders and opens returns inside the 15-day window, for the shopper's own orders only." },
  { step: "Win back", what: "Emails one come-back note for a left cart, with the discount already agreed, and confirms every order." },
  { step: "Escalate", what: "Hands complaints, refunds and “talk to a person” to the team with the full chat." },
];

const RESUME = new URLSearchParams(location.search).get("resume");

export default function Assistant({ customers, health, apiState, prompt }: {
  customers: Customer[]; health: Health; apiState: "waking" | "online" | "offline"; prompt: { text: string; n: number } | null;
}) {
  const [customerId, setCustomerId] = useState<string | null>("C0001");
  // ?tab=ops opens the Ops tab directly, so a link can point at it
  const [tab, setTab] = useState<Tab>(() => (new URLSearchParams(location.search).get("tab") === "ops" ? "ops" : "web"));
  // ?resume=<session> comes from the link in a come-back email: reopen that chat as that shopper
  const [resume, setResume] = useState<string | null>(RESUME);
  const [resumeReady, setResumeReady] = useState(!RESUME);

  useEffect(() => {
    if (!RESUME || resumeReady) return;
    if (apiState === "offline") {  // never leave the chat hidden: fall back to a fresh one
      setResume(null);
      setResumeReady(true);
      return;
    }
    if (apiState !== "online") return;
    api.session(RESUME)
      .then((s) => setCustomerId(s.customer_id))
      .catch(() => setResume(null))
      .finally(() => setResumeReady(true));
  }, [apiState]); // eslint-disable-line react-hooks/exhaustive-deps

  // a tile question waits here until the web chat has sent it, so a remount never resends it
  const [pending, setPending] = useState(prompt);
  useEffect(() => { if (prompt) { setPending(prompt); setTab("web"); } }, [prompt]);

  const status = apiState === "online"
    ? `Online · model ${health?.provider ?? "?"} · emails ${health?.email === "live" ? "sent for real" : "simulated"}`
    : apiState === "waking" ? "Waking the free server, this can take up to a minute…" : "Server unreachable. Refresh in a minute.";

  return (
    <section id="assistant" className="assistant">
      <div className="wrap">
        <div className="assistant-head">
          <p className="badge"><span className="dot" />The heart of this project</p>
          <h2 className="display">Meet ConvoCart</h2>
          <p className="lede">The shopping and support agent behind Kesar Lane. It sells, bargains within limits, tracks
            orders, handles returns and brings shoppers back by email, while every business rule is enforced in code,
            not left to the model.</p>
        </div>

        <ol className="journey">
          {JOURNEY.map((j, i) => (
            <li key={j.step}><span className="n">{i + 1}</span><b>{j.step}</b><p>{j.what}</p></li>
          ))}
        </ol>

        <div className="console">
          <div className="console-bar">
            <div className="tabs" role="tablist" aria-label="View">
              {(["web", "ops"] as Tab[]).map((t) => (
                <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
                  {t === "web" ? "Shop chat" : "Ops team"}
                </button>
              ))}
            </div>
            <label className="persona">
              <span>Shopping as</span>
              <select value={customerId ?? ""} onChange={(e) => { setResume(null); setCustomerId(e.target.value || null); }}>
                <option value="">Guest (not signed in)</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} · {c.city} · {LANG_LABEL[c.preferred_language] ?? c.preferred_language}{c.reminder_opt_in ? "" : " · no email consent"}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className={`status ${apiState}`} role="status"><span className="dot" />{status}</p>

          {tab === "web" && !resumeReady && <p className="muted small resuming">Reopening your cart…</p>}
          {tab === "web" && resumeReady && (
            <Chat key={`${customerId ?? "guest"}:${resume ?? ""}`} customerId={customerId} resumeSid={resume}
              prompt={pending} onPromptUsed={() => setPending(null)} />
          )}
          {tab === "ops" && <Ops />}
        </div>
        <p className="fine">All 200 shoppers, 500 orders and 114 products are invented. Pick any shopper above (each sees
          only their own orders), and type your own address in the cart to receive the emails yourself.</p>
      </div>
    </section>
  );
}
