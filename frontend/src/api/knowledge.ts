import { API_BASE, parseApiError } from "./http";

export interface KnowledgeEvent {
  id: string;
  ts: string;
  type: string;
  symbol?: string | null;
  summary: string;
  headlines?: { 新闻标题?: string; 发布时间?: string }[];
  metrics?: Record<string, number | string>;
}

export interface KnowledgeDelta {
  status: string;
  type: string;
  symbol?: string | null;
  since_days: number;
  new_items: string[];
  removed_items: string[];
  metric_changes: Record<string, unknown>;
  summary: string;
  event_count: number;
}

export interface PolicyDocument {
  id: string;
  title: string;
  filename?: string | null;
  url?: string | null;
  issuer?: string | null;
  symbol?: string | null;
  theme?: string | null;
  source?: string;
  uploaded_at: string;
  chunk_count: number;
  indexed_chunks: number;
}

export interface MemoryHit {
  text?: string;
  score?: number;
  path_id?: string;
  judge_one_liner?: string;
  ts?: string;
  source?: string;
}

export async function fetchKnowledgeEvents(
  type: "sentiment" | "breadth" | "announcement",
  symbol?: string,
  limit = 30,
): Promise<KnowledgeEvent[]> {
  const q = new URLSearchParams({ type, limit: String(limit) });
  if (symbol) q.set("symbol", symbol);
  const res = await fetch(`${API_BASE}/knowledge/events?${q}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = (await res.json()) as { events: KnowledgeEvent[] };
  return data.events;
}

export async function fetchKnowledgeDelta(
  type: "sentiment" | "breadth",
  symbol: string,
  sinceDays = 7,
): Promise<KnowledgeDelta> {
  const q = new URLSearchParams({
    type,
    symbol,
    since_days: String(sinceDays),
  });
  const res = await fetch(`${API_BASE}/knowledge/delta?${q}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<KnowledgeDelta>;
}

export async function fetchPolicyDocuments(): Promise<PolicyDocument[]> {
  const res = await fetch(`${API_BASE}/knowledge/policy`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = (await res.json()) as { documents: PolicyDocument[] };
  return data.documents;
}

export async function uploadPolicyDocument(
  file: File,
  opts?: { title?: string; symbol?: string; theme?: string },
): Promise<{ status: string; doc_id?: string; chunk_count?: number; message?: string }> {
  const form = new FormData();
  form.append("file", file);
  if (opts?.title) form.append("title", opts.title);
  if (opts?.symbol) form.append("symbol", opts.symbol);
  if (opts?.theme) form.append("theme", opts.theme);
  const res = await fetch(`${API_BASE}/knowledge/ingest`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<{ status: string; doc_id?: string; chunk_count?: number; message?: string }>;
}

export async function searchMemory(
  q: string,
  opts?: { namespace?: "knowledge" | "paths"; symbol?: string; type?: string },
): Promise<{ hits: MemoryHit[]; summary: string }> {
  const params = new URLSearchParams({ q, namespace: opts?.namespace ?? "knowledge" });
  if (opts?.symbol) params.set("symbol", opts.symbol);
  if (opts?.type) params.set("type", opts.type);
  const res = await fetch(`${API_BASE}/memory/search?${params}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<{ hits: MemoryHit[]; summary: string }>;
}

export async function reindexMemory(scope: "all" | "paths" = "all"): Promise<{ indexed: number }> {
  const res = await fetch(`${API_BASE}/memory/reindex`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope }),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<{ indexed: number }>;
}
