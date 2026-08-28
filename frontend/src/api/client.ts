import type {
  AgentSummary,
  AnalyzeRequest,
  ComposeRouteResult,
  LlmHealthTier,
  LlmProviderInfo,
  PathIndexEntry,
} from "../types/analysis";
import { API_BASE, parseApiError } from "./http";

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function fetchLlmHealth(): Promise<Record<string, LlmHealthTier>> {
  const res = await fetch(`${API_BASE}/llm/health`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function fetchLlmProviders(): Promise<LlmProviderInfo[]> {
  const res = await fetch(`${API_BASE}/llm/providers`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = await res.json();
  return data.providers ?? [];
}

export async function fetchAgents(): Promise<AgentSummary[]> {
  const res = await fetch(`${API_BASE}/agents`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = await res.json();
  return data.agents ?? [];
}

export async function fetchPaths(): Promise<PathIndexEntry[]> {
  const res = await fetch(`${API_BASE}/paths`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = await res.json();
  return data.paths ?? [];
}

export async function fetchPath(pathId: string): Promise<{
  meta: PathIndexEntry;
  steps: import("../types/analysis").AnalysisStep[];
  snapshots?: import("../types/analysis").ContextSnapshot[];
  reports?: import("../lib/ticketSummary").PathReports | null;
}> {
  const res = await fetch(`${API_BASE}/paths/${pathId}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function deletePath(pathId: string, force = false): Promise<void> {
  const url = force
    ? `${API_BASE}/paths/${pathId}?force=true`
    : `${API_BASE}/paths/${pathId}`;
  const res = await fetch(url, { method: "DELETE" });
  if (!res.ok) throw new Error(await parseApiError(res));
}

export async function cancelAnalysis(pathId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/analyze/cancel/${pathId}`, { method: "POST" });
  if (!res.ok) throw new Error(await parseApiError(res));
}

export function analyzeStreamUrl(): string {
  return `${API_BASE}/analyze/stream`;
}

export function serializeAnalyzeRequest(req: AnalyzeRequest): string {
  return JSON.stringify(req);
}

export async function routeCompose(body: AnalyzeRequest): Promise<ComposeRouteResult> {
  const res = await fetch(`${API_BASE}/compose/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: serializeAnalyzeRequest(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export interface OhlcvBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface OhlcvResponse {
  symbol: string;
  limit: number;
  window_label: string;
  bars: OhlcvBar[];
  summary?: Record<string, unknown>;
}

export async function fetchOhlcv(
  symbol: string,
  options?: { limit?: number; message?: string; focus?: string | null },
): Promise<OhlcvResponse> {
  const params = new URLSearchParams();
  if (options?.limit != null) params.set("limit", String(options.limit));
  if (options?.message) params.set("message", options.message);
  if (options?.focus) params.set("focus", options.focus);
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/quotes/${encodeURIComponent(symbol)}/ohlcv${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}
