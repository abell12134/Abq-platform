import type { AnalysisStep } from "../types/analysis";
import { agentLabel } from "./agentLabels";

export type WorkflowPhaseId = "data" | "views" | "debate" | "judge" | "other";

export interface WorkflowParallelLane {
  id: string;
  label: string;
  steps: AnalysisStep[];
}

export interface WorkflowPhaseGroup {
  id: WorkflowPhaseId;
  label: string;
  steps: AnalysisStep[];
  parallel?: boolean;
  lanes?: WorkflowParallelLane[];
}

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
const VIEW_AGENTS = new Set(["tech", "fundamental", "sentiment", "market", "portfolio"]);
const DEBATE_AGENTS = new Set(["bull", "bear"]);
const JUDGE_AGENTS = new Set(["judge", "supervisor"]);

const VIEW_LANE_ORDER = ["tech", "fundamental", "sentiment", "market", "portfolio"] as const;
const DEBATE_LANE_ORDER = ["bull", "bear"] as const;

const PHASE_LABELS: Record<WorkflowPhaseId, string> = {
  data: "数据阶段",
  views: "视角分析（并行）",
  debate: "多空辩论（并行）",
  judge: "综合研判",
  other: "用户 / 其他",
};

export function stepPhase(step: AnalysisStep): WorkflowPhaseId {
  if (step.role === "user") return "other";
  if (DATA_AGENTS.has(step.agent)) return "data";
  if (VIEW_AGENTS.has(step.agent)) return "views";
  if (DEBATE_AGENTS.has(step.agent)) return "debate";
  if (JUDGE_AGENTS.has(step.agent)) return "judge";
  return "other";
}

function withParallelLanes(
  group: WorkflowPhaseGroup,
  laneOrder: readonly string[],
): WorkflowPhaseGroup {
  const lanes = laneOrder
    .map((id) => ({
      id,
      label: agentLabel(id),
      steps: group.steps.filter((s) => s.agent === id),
    }))
    .filter((lane) => lane.steps.length > 0);
  if (lanes.length <= 1) return group;
  return { ...group, parallel: true, lanes };
}

export function groupWorkflowSteps(steps: AnalysisStep[]): WorkflowPhaseGroup[] {
  const order: WorkflowPhaseId[] = ["other", "data", "views", "debate", "judge"];
  const buckets = new Map<WorkflowPhaseId, AnalysisStep[]>();
  for (const id of order) buckets.set(id, []);

  for (const step of steps) {
    const phase = stepPhase(step);
    buckets.get(phase)!.push(step);
  }

  return order
    .map((id) => ({ id, label: PHASE_LABELS[id], steps: buckets.get(id)! }))
    .filter((g) => g.steps.length > 0)
    .map((group) => {
      if (group.id === "views") return withParallelLanes(group, VIEW_LANE_ORDER);
      if (group.id === "debate") return withParallelLanes(group, DEBATE_LANE_ORDER);
      return group;
    });
}
