import type { MemoryPreviewResult } from "../types/analysis";
import { API_BASE, parseApiError } from "./http";

export async function fetchMemoryPreview(params: {
  message: string;
  kind?: string;
  symbol?: string | null;
  focus?: string | null;
}): Promise<MemoryPreviewResult> {
  const q = new URLSearchParams({ message: params.message, kind: params.kind ?? "single" });
  if (params.symbol) q.set("symbol", params.symbol);
  if (params.focus) q.set("focus", params.focus);
  const res = await fetch(`${API_BASE}/memory/preview?${q}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json() as Promise<MemoryPreviewResult>;
}
