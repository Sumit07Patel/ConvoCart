export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export type ToolCall = { agent: string; name: string; args: Record<string, unknown>; ok: boolean; error: string | null };
export type CartItem = { variant_id: string; product_id: string; title: string; size: string; color: string; qty: number; unit_price: number; line_total: number };
export type Cart = { id: string; status: string; items: CartItem[]; subtotal: number; discount_pct: number; discount_amount: number; total: number };
export type ChatResponse = {
  session_id: string; trace_id: string; reply: string; language: string; route: string; handover: boolean;
  handover_reason: string | null; status: string; issues: Record<string, unknown>; cart: Cart | null;
  latency_ms: number; tool_calls: ToolCall[];
};
export type Customer = { id: string; name: string; phone: string; email: string; city: string; preferred_language: string; reminder_opt_in: boolean };
export type HistoryMsg = { role: "user" | "assistant"; content: string };
export type SentEmail = { id: number; to: string; purpose: string; subject: string; body: string; status: string; detail: string; created_at: string };
export type Order = { id: string; total: number; status: string; items: { title: string; qty: number; unit_price: number }[] };
export type Handover = { id: number; session_id: string; customer_id: string | null; reason: string; status: string; created_at: string; summary: { last_messages?: HistoryMsg[]; language?: string; cart_id?: string } };
export type Approval = { id: number; kind: string; ref_id: string; customer_id: string; amount: number; status: string; details: Record<string, string>; created_at: string };
export type TraceEvent = { trace_id: string; kind: string; agent: string; name: string; payload: Record<string, unknown>; latency_ms: number };

async function req<T>(path: string, init: RequestInit = {}, admin?: string): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (admin) headers["x-admin-token"] = admin;
  const r = await fetch(`${API_URL}${path}`, { ...init, headers: { ...headers, ...(init.headers as Record<string, string> | undefined) } });
  if (!r.ok) {
    const text = await r.text();
    let detail = text;
    try { detail = (JSON.parse(text) as { detail?: string }).detail ?? text; } catch { /* not JSON */ }
    throw new Error(`${r.status} ${detail}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => req<{ ok: boolean; provider: string; email: string }>("/health"),
  customers: () => req<Customer[]>("/demo/customers"),
  chat: (message: string, session_id: string | null, customer_id: string | null) =>
    req<ChatResponse>("/chat", { method: "POST", body: JSON.stringify({ message, session_id, customer_id }) }),
  session: (sid: string) => req<{ history: HistoryMsg[]; cart: Cart | null; status: string; customer_id: string | null }>(`/sessions/${encodeURIComponent(sid)}`),
  contact: (sid: string, email: string, consent: boolean) =>
    req<{ email: string; consent: boolean }>(`/sessions/${encodeURIComponent(sid)}/contact`, { method: "POST", body: JSON.stringify({ email, consent }) }),
  emails: (sid: string) => req<SentEmail[]>(`/sessions/${encodeURIComponent(sid)}/emails`),
  pay: (sid: string) => req<{ order: Order; email: { status: string; to?: string; detail?: string } }>(`/demo/pay/${encodeURIComponent(sid)}`, { method: "POST" }),
  traces: (sid: string) => req<TraceEvent[]>(`/sessions/${encodeURIComponent(sid)}/traces`),
  abandon: (session_id: string) => req<{ job: { results?: { status: string; detail: string }[] } }>("/demo/abandon", { method: "POST", body: JSON.stringify({ session_id }) }),
  handovers: (t: string) => req<Handover[]>("/admin/handovers", {}, t),
  closeHandover: (id: number, t: string) => req(`/admin/handovers/${id}/close`, { method: "POST" }, t),
  replyHandover: (id: number, text: string, t: string) => req(`/admin/handovers/${id}/reply`, { method: "POST", body: JSON.stringify({ text }) }, t),
  approvals: (t: string) => req<Approval[]>("/admin/approvals", {}, t),
  decide: (id: number, approve: boolean, t: string) => req(`/admin/approvals/${id}`, { method: "POST", body: JSON.stringify({ approve, decided_by: "demo-ops" }) }, t),
  metrics: (t: string) => req<Record<string, number | null>>("/admin/metrics", {}, t),
};
