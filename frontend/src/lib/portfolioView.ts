import type { PathIndexEntry } from "../types/analysis";

const KIND_BADGE: Record<string, string> = {
  single: "单票",
  market: "大盘",
  portfolio: "选组",
};

export function pathKindBadge(kind: PathIndexEntry["kind"]): string | null {
  return KIND_BADGE[kind] ?? null;
}

export function formatPct(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function pctTone(value: number | null | undefined): "up" | "down" | "flat" {
  if (value == null || Number.isNaN(value) || Math.abs(value) < 0.005) return "flat";
  return value > 0 ? "up" : "down";
}

export function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value >= 100 ? value.toFixed(2) : value.toFixed(3);
}
