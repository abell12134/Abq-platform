import type { AnalysisStep } from "../types/analysis";
import { parseFactorSummary, type FactorSnapshot, type PathReports } from "./ticketSummary";
import { formatPct } from "./portfolioView";

export interface PortfolioMemberRow {
  symbol: string;
  name?: string | null;
  price?: number | null;
  pct_change?: number | null;
  chg_5d?: number | null;
  chg_20d?: number | null;
  note?: string | null;
}

export interface PortfolioSummary {
  name: string | null;
  memberCount: number;
  equalWeightPct1d: number | null;
  equalWeightChg5d: number | null;
  equalWeightChg20d: number | null;
  members: PortfolioMemberRow[];
  bestToday: PortfolioMemberRow | null;
  worstToday: PortfolioMemberRow | null;
  portfolioReport: string | null;
  judge: string | null;
  factors: FactorSnapshot[];
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

function parseMembers(payload: Record<string, unknown> | null): PortfolioMemberRow[] {
  if (!payload) return [];
  const members = payload.members;
  if (!Array.isArray(members)) return [];
  return members.map((m) => {
    const row = m as Record<string, unknown>;
    return {
      symbol: String(row.symbol ?? ""),
      name: row.name as string | null | undefined,
      price: row.price as number | null | undefined,
      pct_change: row.pct_change as number | null | undefined,
      chg_5d: row.chg_5d as number | null | undefined,
      chg_20d: row.chg_20d as number | null | undefined,
      note: row.note as string | null | undefined,
    };
  });
}

export function buildPortfolioSummary(
  steps: AnalysisStep[],
  reports?: PathReports | null,
): PortfolioSummary {
  const quotesPayload = lastToolPayload(steps, "fetch_portfolio_quotes");
  const members = parseMembers(quotesPayload);
  const portfolioName =
    (quotesPayload?.portfolio as string | undefined) ??
    (quotesPayload?.name as string | undefined) ??
    null;

  const pctValues = members
    .map((m) => m.pct_change)
    .filter((v): v is number => typeof v === "number");
  const chg5 = members.map((m) => m.chg_5d).filter((v): v is number => typeof v === "number");
  const chg20 = members.map((m) => m.chg_20d).filter((v): v is number => typeof v === "number");
  const avg = (vals: number[]) => (vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null);

  const sorted = [...members].filter((m) => typeof m.pct_change === "number");
  sorted.sort((a, b) => (b.pct_change ?? 0) - (a.pct_change ?? 0));

  const extReports = reports as PathReports & {
    portfolio?: { content: string };
    portfolio_summary?: string | null;
  };

  return {
    name: portfolioName,
    memberCount: members.length,
    equalWeightPct1d: avg(pctValues),
    equalWeightChg5d: avg(chg5),
    equalWeightChg20d: avg(chg20),
    members,
    bestToday: sorted[0] ?? null,
    worstToday: sorted.length ? sorted[sorted.length - 1]! : null,
    portfolioReport:
      lastAssistantBody(steps, "portfolio") ?? extReports?.portfolio?.content ?? null,
    judge: lastAssistantBody(steps, "judge") ?? reports?.judge?.content ?? null,
    factors: parseFactorSummary(reports?.factor_summary),
  };
}

export { formatPct };
