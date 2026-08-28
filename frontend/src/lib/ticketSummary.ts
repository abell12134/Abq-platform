import type { AnalysisStep } from "../types/analysis";

export interface TicketQuote {
  symbol: string;
  name?: string;
  price?: number;
  pct_change?: number;
  change?: number;
  prev_close?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  as_of?: string | null;
  status?: string;
}

export interface TicketIndicators {
  as_of?: string;
  close?: number;
  pct_1d?: number;
  pct_5d?: number;
  pct_20d?: number;
  ma5?: number;
  ma10?: number;
  ma20?: number;
  vol_ratio_5d?: number;
  [key: string]: unknown;
}

export interface TicketSummary {
  symbol: string | null;
  quote: TicketQuote | null;
  indicators: TicketIndicators | null;
  views: Partial<Record<"tech" | "fundamental" | "sentiment", string>>;
  judge: string | null;
  userQuestions: string[];
  factors: FactorSnapshot[];
}

export interface FactorSnapshot {
  id: string;
  name: string;
  raw: string;
  percentile: string;
}

function parseJsonStep(step: AnalysisStep): Record<string, unknown> | null {
  try {
    return JSON.parse(step.result) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function lastToolPayload(steps: AnalysisStep[], agent: string): Record<string, unknown> | null {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i]!;
    if (step.role === "tool" && step.agent === agent) {
      return parseJsonStep(step);
    }
  }
  return null;
}

function lastAssistantBody(steps: AnalysisStep[], agent: string): string | null {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i]!;
    if (step.role === "assistant" && step.agent === agent) {
      const body = (step.result || step.thought).trim();
      if (body && body !== "（模型未返回文本）") return body;
    }
  }
  return null;
}

export interface PathReports {
  tech?: { content: string };
  fundamental?: { content: string };
  sentiment?: { content: string };
  bull?: { content: string };
  bear?: { content: string };
  judge?: { content: string };
  factor_summary?: string | null;
}

const FACTOR_LINE_RE =
  /^- \*\*(.+?)\*\* \(`([^`]+)`\): 值=([^，]+)，截面分位=(.+)$/;

export function parseFactorSummary(text: string | null | undefined): FactorSnapshot[] {
  if (!text?.trim()) return [];
  const out: FactorSnapshot[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    const match = trimmed.match(FACTOR_LINE_RE);
    if (!match) continue;
    out.push({
      name: match[1]!,
      id: match[2]!,
      raw: match[3]!,
      percentile: match[4]!,
    });
  }
  return out;
}

export function buildTicketSummary(
  steps: AnalysisStep[],
  reports?: PathReports | null,
): TicketSummary {
  const quoteRaw = lastToolPayload(steps, "fetch_quote");
  const indicatorRaw = lastToolPayload(steps, "calc_indicator");

  const quote: TicketQuote | null = quoteRaw
    ? {
        symbol: String(quoteRaw.symbol ?? ""),
        name: quoteRaw.name as string | undefined,
        price: quoteRaw.price as number | undefined,
        pct_change: quoteRaw.pct_change as number | undefined,
        change: quoteRaw.change as number | undefined,
        prev_close: quoteRaw.prev_close as number | undefined,
        open: quoteRaw.open as number | undefined,
        high: quoteRaw.high as number | undefined,
        low: quoteRaw.low as number | undefined,
        volume: quoteRaw.volume as number | undefined,
        as_of: quoteRaw.as_of as string | null | undefined,
        status: quoteRaw.status as string | undefined,
      }
    : null;

  const indicators = indicatorRaw
    ? ({
        as_of: indicatorRaw.as_of as string | undefined,
        close: indicatorRaw.close as number | undefined,
        ma5: indicatorRaw.ma5 as number | undefined,
        ma10: indicatorRaw.ma10 as number | undefined,
        ma20: indicatorRaw.ma20 as number | undefined,
        pct_1d: (indicatorRaw.pct_change_1d ?? indicatorRaw.pct_1d) as number | undefined,
        pct_5d: (indicatorRaw.pct_change_5d ?? indicatorRaw.pct_5d) as number | undefined,
        pct_20d: (indicatorRaw.pct_change_20d ?? indicatorRaw.pct_20d) as number | undefined,
        vol_ratio_5d: (indicatorRaw.volume_ratio_5d ?? indicatorRaw.vol_ratio_5d) as
          | number
          | undefined,
        summary: indicatorRaw.summary,
      } as TicketIndicators)
    : null;

  const symbol =
    quote?.symbol ??
    (indicatorRaw?.symbol as string | undefined) ??
    steps.find((s) => s.tool_calls[0]?.output_ref)?.tool_calls[0]?.output_ref ??
    null;

  const userQuestions = steps
    .filter((s) => s.role === "user")
    .map((s) => s.result.trim())
    .filter(Boolean);

  return {
    symbol,
    quote,
    indicators,
    views: {
      tech: lastAssistantBody(steps, "tech") ?? reports?.tech?.content,
      fundamental: lastAssistantBody(steps, "fundamental") ?? reports?.fundamental?.content,
      sentiment: lastAssistantBody(steps, "sentiment") ?? reports?.sentiment?.content,
    },
    judge: lastAssistantBody(steps, "judge") ?? reports?.judge?.content ?? null,
    userQuestions,
    factors: parseFactorSummary(reports?.factor_summary),
  };
}

export function formatPct(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatPrice(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

export function formatAsOf(value?: string | null): string {
  if (!value) return "";
  return value.slice(0, 19).replace("T", " ");
}

export function formatVolume(value?: number): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return String(Math.round(value));
}

export function quoteFeedLabel(status?: string, asOf?: string | null): string {
  const raw = (status ?? "").trim();
  const s = raw.toLowerCase();
  if (/open|trading|交易|开盘/.test(s)) return "交易中";
  if (/halt|停牌/.test(s) || /停牌/.test(raw)) return "停牌";
  if (/close|closed|收盘/.test(s)) return "已收盘";
  if (raw) return raw;
  return asOf ? "快照" : "—";
}
