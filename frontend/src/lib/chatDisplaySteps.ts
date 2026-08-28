import type { AnalysisStep } from "../types/analysis";
import { agentLabel } from "./agentLabels";

const DATA_AGENTS = new Set([
  "fetch_quote",
  "fetch_ohlcv",
  "clean_data",
  "calc_indicator",
  "fetch_fundamentals",
  "fetch_sentiment",
  "fetch_market_breadth",
  "fetch_sector_pulse",
  "fetch_portfolio_quotes",
]);

const MINE_AGENTS = new Set([
  "start_factor_mine_llm",
  "start_factor_mine_gp",
  "get_factor_mine_status",
]);

const SCREEN_CARD_AGENTS = new Set(["run_factor_screen", "apply_screen_to_portfolio"]);

export type ChatThreadItem =
  | { kind: "step"; step: AnalysisStep }
  | { kind: "tool-group"; id: string; steps: AnalysisStep[]; symbol?: string };

/** Keep only the latest data-tool step per agent within each user turn. */
export function dedupeDataToolSteps(steps: AnalysisStep[]): AnalysisStep[] {
  const out: AnalysisStep[] = [];
  let turn: AnalysisStep[] = [];

  const flushTurn = () => {
    if (!turn.length) return;
    const latestByAgent = new Map<string, AnalysisStep>();
    for (const step of turn) {
      if (step.role === "tool" && DATA_AGENTS.has(step.agent)) {
        latestByAgent.set(step.agent, step);
      }
    }
    const keepIds = new Set([...latestByAgent.values()].map((s) => s.id));
    for (const step of turn) {
      if (step.role === "tool" && DATA_AGENTS.has(step.agent)) {
        if (keepIds.has(step.id)) out.push(step);
      } else {
        out.push(step);
      }
    }
    turn = [];
  };

  for (const step of steps) {
    if (step.role === "user") {
      flushTurn();
      out.push(step);
      continue;
    }
    turn.push(step);
  }
  flushTurn();
  return out;
}

/** Chat thread: keep user + tool steps, only the last assistant turn per agent. */
export function selectChatSteps(steps: AnalysisStep[]): AnalysisStep[] {
  if (!steps.length) return [];

  const lastAssistantByAgent = new Map<string, AnalysisStep>();
  for (const step of steps) {
    if (step.role === "assistant") {
      lastAssistantByAgent.set(step.agent, step);
    }
  }

  return steps.filter((step) => {
    if (step.role === "tool" && MINE_AGENTS.has(step.agent)) return false;
    if (step.role === "tool" && SCREEN_CARD_AGENTS.has(step.agent)) return true;
    if (step.role === "user" || step.role === "tool") return true;
    if (step.role !== "assistant") return true;
    return lastAssistantByAgent.get(step.agent)?.id === step.id;
  });
}

export function buildChatThread(steps: AnalysisStep[]): ChatThreadItem[] {
  const filtered = selectChatSteps(dedupeDataToolSteps(steps));
  const items: ChatThreadItem[] = [];
  let dataBuffer: AnalysisStep[] = [];

  const flushData = () => {
    if (!dataBuffer.length) return;
    const symbol = dataBuffer.find((s) => s.tool_calls[0]?.output_ref)?.tool_calls[0]
      ?.output_ref;
    items.push({
      kind: "tool-group",
      id: `data-${dataBuffer[0]!.id}`,
      steps: [...dataBuffer],
      symbol: symbol ?? undefined,
    });
    dataBuffer = [];
  };

  for (const step of filtered) {
    if (step.role === "tool" && DATA_AGENTS.has(step.agent)) {
      dataBuffer.push(step);
      continue;
    }
    flushData();
    items.push({ kind: "step", step });
  }
  flushData();
  return items;
}

export function stepDefaultCollapsed(step: AnalysisStep, streamActiveIds?: Record<string, boolean>): boolean {
  if (streamActiveIds?.[step.id]) return false;
  if (step.role === "user") return false;
  if (step.agent === "judge") return false;
  if (step.role === "assistant") return step.agent !== "judge";
  return true;
}

export function stepAgentTone(agent: string): string {
  if (agent === "tech") return "tone-tech";
  if (agent === "fundamental") return "tone-fundamental";
  if (agent === "sentiment") return "tone-sentiment";
  if (agent === "judge") return "tone-judge";
  if (DATA_AGENTS.has(agent)) return "tone-data";
  return "tone-default";
}

export function stepPreview(step: AnalysisStep): string {
  if (step.role === "tool") {
    const ref = step.tool_calls[0]?.output_ref;
    if (ref) return `已获取 ${ref}`;
    const raw = (step.result || "").trim();
    if (!raw) return agentLabel(step.agent);
    return raw.length > 72 ? `${raw.slice(0, 72)}…` : raw;
  }

  const text = (step.result || step.thought || "").trim();
  if (!text) return agentLabel(step.agent);

  const conclusion = text.match(/##\s*结论\s*\n+([\s\S]*?)(?=\n##|\n$|$)/);
  if (conclusion?.[1]) {
    const line =
      conclusion[1]
        .split(/\r?\n/)
        .find((l) => l.trim())?.trim() ?? conclusion[1].trim();
    const plain = line.replace(/^[-*]\s*/, "").replace(/\*\*/g, "");
    return plain.length > 120 ? `${plain.slice(0, 120)}…` : plain;
  }

  const firstLine = text.split(/\r?\n/).find((line) => line.trim())?.trim() ?? text;
  const plain = firstLine.replace(/^#+\s*/, "").replace(/\*\*/g, "");
  return plain.length > 96 ? `${plain.slice(0, 96)}…` : plain;
}

export function stepBadge(step: AnalysisStep): string | null {
  const text = (step.result || step.thought || "").trim();
  if (!text) return null;

  const stance = text.match(/立场[：:]\s*\*?\*?([^*\n（(]+)/);
  if (stance?.[1]) return stance[1].trim();

  if (step.agent === "sentiment") {
    try {
      const jsonMatch = text.match(/\{[\s\S]*"sentiment"[\s\S]*\}\s*$/);
      if (jsonMatch) {
        const parsed = JSON.parse(jsonMatch[0]) as { sentiment?: string; stance?: string };
        if (parsed.stance) return parsed.stance;
        if (parsed.sentiment) return parsed.sentiment;
      }
    } catch {
      /* ignore */
    }
  }

  return null;
}
