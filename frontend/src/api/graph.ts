import { API_BASE, parseApiError } from "./http";

export interface GraphNode {
  id: string;
  type: string;
  label: string;
  props: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  src: string;
  dst: string;
  type: string;
  props: Record<string, unknown>;
}

export interface GraphSubgraph {
  center: string;
  hops: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphStats {
  node_count: number;
  edge_count: number;
  nodes_by_type: Record<string, number>;
  last_bootstrap_at?: string | null;
  sample_symbols: string[];
}

export interface GraphSyncResult {
  status: string;
  requested: number;
  synced: number;
  skipped: number;
  errors: number;
  min_interval_s: number;
  cooldown_hours: number;
  summary: string;
  results: {
    symbol: string;
    status: string;
    skipped: boolean;
    reason: string;
    company_name?: string | null;
    sector?: string | null;
    news_linked: number;
  }[];
}

export async function fetchGraphStats(): Promise<GraphStats> {
  const res = await fetch(`${API_BASE}/graph/stats`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<GraphStats>;
}

export async function fetchGraphSubgraph(
  center: string,
  hops = 1,
): Promise<GraphSubgraph> {
  const q = new URLSearchParams({ center, hops: String(hops) });
  const res = await fetch(`${API_BASE}/graph/subgraph?${q}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<GraphSubgraph>;
}

export async function syncGraphSample(opts?: {
  symbols?: string;
  force?: boolean;
}): Promise<GraphSyncResult> {
  const q = new URLSearchParams();
  if (opts?.symbols) q.set("symbols", opts.symbols);
  if (opts?.force) q.set("force", "true");
  const res = await fetch(`${API_BASE}/graph/sync?${q}`, { method: "POST" });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<GraphSyncResult>;
}

export interface RollupResult {
  status: string;
  period: string;
  scope: string;
  key: string;
  digest_id: string;
  event_count: number;
  summary: string;
  used_llm: boolean;
  skipped?: boolean;
}

export interface IncrementalSyncResult {
  status: string;
  symbol: string;
  summary: string;
  stock: GraphSyncResult["results"][0] & { status: string; skipped?: boolean; reason?: string };
  market: Record<string, unknown>;
  policy: Record<string, unknown>;
  rollup: RollupResult;
}

export async function syncGraphIncremental(
  symbol: string,
  opts?: { force?: boolean },
): Promise<IncrementalSyncResult> {
  const q = new URLSearchParams({ symbol });
  if (opts?.force) q.set("force", "true");
  const res = await fetch(`${API_BASE}/graph/sync/incremental?${q}`, { method: "POST" });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<IncrementalSyncResult>;
}

export async function rollupGraphMonth(opts?: {
  period?: string;
  scope?: string;
  key: string;
  useLlm?: boolean;
}): Promise<RollupResult> {
  const period =
    opts?.period ?? new Date().toISOString().slice(0, 7);
  const res = await fetch(`${API_BASE}/graph/rollup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      period,
      scope: opts?.scope ?? "symbol",
      key: opts?.key,
      use_llm: opts?.useLlm,
    }),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<RollupResult>;
}

export async function rollupGraphCurrentMonth(symbols?: string): Promise<{
  status: string;
  period: string | null;
  results: RollupResult[];
}> {
  const q = symbols ? `?symbols=${encodeURIComponent(symbols)}` : "";
  const res = await fetch(`${API_BASE}/graph/rollup/month${q}`, { method: "POST" });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<{
    status: string;
    period: string | null;
    results: RollupResult[];
  }>;
}

export async function ingestPolicyUrl(body: {
  url: string;
  title?: string;
  symbol?: string;
  theme?: string;
  issuer?: string;
}): Promise<{ status: string; doc_id?: string; message?: string; url?: string }> {
  const res = await fetch(`${API_BASE}/knowledge/ingest/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<{ status: string; doc_id?: string; message?: string; url?: string }>;
}

export async function fetchPolicyHosts(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/knowledge/policy/hosts`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = (await res.json()) as { hosts: string[] };
  return data.hosts;
}

export async function syncGraphMarket(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/graph/sync/market`, { method: "POST" });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<Record<string, unknown>>;
}

export async function syncPolicySources(opts?: {
  sourceId?: string;
  maxTotal?: number;
}): Promise<Record<string, unknown>> {
  const q = new URLSearchParams();
  if (opts?.sourceId) q.set("source_id", opts.sourceId);
  if (opts?.maxTotal != null) q.set("max_total", String(opts.maxTotal));
  const suffix = q.toString() ? `?${q}` : "";
  const res = await fetch(`${API_BASE}/graph/policy/sync${suffix}`, { method: "POST" });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<Record<string, unknown>>;
}

export async function runGraphMaintenance(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/graph/maintenance`, { method: "POST" });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<Record<string, unknown>>;
}
