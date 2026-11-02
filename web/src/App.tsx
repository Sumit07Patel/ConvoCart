import { useEffect, useState } from "react";
import { api, type Customer } from "./api";
import Brand from "./Brand";
import Assistant from "./Assistant";
import Project from "./Project";

export type Health = { provider: string; email: string } | null;

export default function App() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [health, setHealth] = useState<Health>(null);
  const [apiState, setApiState] = useState<"waking" | "online" | "offline">("waking");
  // a prompt sent from anywhere on the page (collection tiles, hero) into the web chat
  const [prompt, setPrompt] = useState<{ text: string; n: number } | null>(null);
  const [onAi, setOnAi] = useState(false);
  const [onAbout, setOnAbout] = useState(false);

  // the free Render service sleeps when idle; keep trying while it wakes (about 2 minutes at most)
  useEffect(() => {
    let stop = false;
    (async () => {
      for (let i = 0; i < 12 && !stop; i++) {
        try {
          const h = await api.health();
          if (stop) return;
          setHealth(h);
          setApiState("online");
          setCustomers(await api.customers());
          return;
        } catch {
          await new Promise((r) => setTimeout(r, 10000));
        }
      }
      if (!stop) setApiState("offline");
    })();
    return () => { stop = true; };
  }, []);

  // header switch shows whether the visitor is at the assistant or the project write-up
  useEffect(() => {
    let queued = false;
    const mark = () => {
      queued = false;
      const h = window.innerHeight;
      const sup = document.getElementById("assistant")?.getBoundingClientRect();
      const proj = document.getElementById("project")?.getBoundingClientRect();
      if (!sup || !proj) return;
      const about = proj.top < h * 0.5;
      setOnAbout(about);
      setOnAi(!about && sup.top < h * 0.5 && sup.bottom > h * 0.25);
    };
    const onScroll = () => { if (!queued) { queued = true; requestAnimationFrame(mark); } };
    addEventListener("scroll", onScroll, { passive: true });
    addEventListener("resize", mark);
    mark();
    return () => { removeEventListener("scroll", onScroll); removeEventListener("resize", mark); };
  }, []);

  function ask(text: string) {
    setPrompt({ text, n: Date.now() });
    document.getElementById("assistant")?.scrollIntoView({ behavior: "smooth" });
  }

  return (
    <>
      <p className="announce">New: The Monsoon Edit · 15-day easy returns · Shop in English, हिंदी or Hinglish</p>
      <header className="site-head">
        <nav className="wrap nav" aria-label="Main">
          <ul className="nav-links">
            <li><a href="#collections">Monsoon</a></li>
            <li><a href="#collections">Ethnic</a></li>
            <li><a href="#collections">Footwear</a></li>
            <li><a href="#collections">Winter</a></li>
            <li><a href="#collections">Basics</a></li>
          </ul>
          <a href="#top" className="wordmark">Kesar Lane</a>
          <div className="jump" role="group" aria-label="Jump to">
            <a href="#assistant" aria-current={onAi}><span className="live" aria-hidden="true" />Ask AI</a>
            <a href="#project" aria-current={onAbout}>About project</a>
          </div>
        </nav>
      </header>

      <main id="top">
        <Brand onAsk={ask} />
        <Assistant customers={customers} health={health} apiState={apiState} prompt={prompt} />
      </main>

      <Project health={health} />

      {!onAi && (
        <a href="#assistant" className="fab"><span className="live" aria-hidden="true" />Ask ConvoCart</a>
      )}
    </>
  );
}
