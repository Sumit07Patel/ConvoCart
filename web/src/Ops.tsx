import { useCallback, useEffect, useState } from "react";
import { api, type Approval, type Handover } from "./api";

export default function Ops() {
  const [token, setToken] = useState("dev-admin-token");
  const [handovers, setHandovers] = useState<Handover[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [metrics, setMetrics] = useState<Record<string, number | null> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    try {
      setErr(null);
      const [h, a, m] = await Promise.all([api.handovers(token), api.approvals(token), api.metrics(token)]);
      setHandovers(h); setApprovals(a); setMetrics(m);
    } catch (e) {
      setErr(String(e));
    }
  }, [token]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="ops">
      <div className="ops-bar">
        <label>Admin token <input value={token} onChange={(e) => setToken(e.target.value)} /></label>
        <button onClick={() => void load()}>Refresh</button>
      </div>
      {err && (
        <div className="error">
          {/^(401|403)/.test(err)
            ? "The Ops view is for the store team and needs the admin token. On the live demo it is private; run the project locally to try approvals and handovers."
            : err}
        </div>
      )}
      {metrics && (
        <div className="metrics">
          <div><b>{metrics.sessions}</b><span>sessions</span></div>
          <div><b>{metrics.deflection_rate == null ? "–" : `${Math.round((metrics.deflection_rate as number) * 100)}%`}</b><span>resolved without a human</span></div>
          <div><b>{metrics.latency_ms_p50 ?? "–"} ms</b><span>median turn</span></div>
          <div><b>{metrics.latency_ms_p95 ?? "–"} ms</b><span>95th percentile</span></div>
          <div><b>{metrics.open_handovers}</b><span>open handovers</span></div>
          <div><b>{metrics.pending_approvals}</b><span>refunds awaiting approval</span></div>
        </div>
      )}
      <div className="ops-cols">
        <section className="card">
          <h3>Refund approvals</h3>
          {approvals.length === 0 && <p className="muted">Nothing waiting.</p>}
          {approvals.map((a) => (
            <div key={a.id} className="row">
              <div><b>{a.ref_id}</b> · order {a.details.order_id} · ₹{a.amount}<br /><small className="muted">{a.customer_id} · “{a.details.reason}”</small></div>
              <div className="btns">
                <button onClick={async () => { await api.decide(a.id, true, token); void load(); }}>Approve</button>
                <button className="ghost" onClick={async () => { await api.decide(a.id, false, token); void load(); }}>Reject</button>
              </div>
            </div>
          ))}
        </section>
        <section className="card">
          <h3>Handovers</h3>
          {handovers.length === 0 && <p className="muted">No open handovers.</p>}
          {handovers.map((h) => (
            <div key={h.id} className="handover">
              <div className="small"><b>#{h.id}</b> {h.session_id} · {h.customer_id ?? "guest"} · <i>{h.reason}</i></div>
              <div className="mini-thread">
                {(h.summary.last_messages ?? []).map((m, i) => <div key={i} className={`mini ${m.role}`}>{m.content}</div>)}
              </div>
              <div className="reply">
                <input value={drafts[h.id] ?? ""} onChange={(e) => setDrafts({ ...drafts, [h.id]: e.target.value })} placeholder="Reply as the team…" />
                <button onClick={async () => { await api.replyHandover(h.id, drafts[h.id] ?? "", token); setDrafts({ ...drafts, [h.id]: "" }); }}>Reply</button>
                <button className="ghost" onClick={async () => { await api.closeHandover(h.id, token); void load(); }}>Close, back to bot</button>
              </div>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
