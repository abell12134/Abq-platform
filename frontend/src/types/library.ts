import type { ModelTier } from "./analysis";

export type PromptCategory = "agent-persona" | "analysis" | "extraction" | "summary";
export type AgentStatus = "active" | "draft";
export type LibraryTab = "agents" | "prompts" | "tools" | "factors" | "screener" | "knowledge";

export type FactorOrigin = "catalog" | "manual" | "llm" | "gp" | "synth";
export type FactorStatus =
  | "candidate"
  | "rejected"
  | "passed_auto"
  | "paper_tracking"
  | "frozen"
  | "retired"
  | "live";
export type FactorUniverse = "csi300" | "csi500" | "market";

export interface FactorRecord {
  id: string;
  name: string;
  origin: FactorOrigin;
  status: FactorStatus;
  theme: string[];
  universe: FactorUniverse;
  formula: string;
  expr: Record<string, unknown>;
  hypothesis: string;
  forward_days: number;
  metrics: Record<string, unknown>;
  reject_reason: string;
  builtin: boolean;
  created_at: string;
  updated_at: string;
}

export interface FactorCreate {
  id: string;
  name: string;
  formula: string;
  hypothesis?: string;
  theme?: string[];
  universe?: FactorUniverse;
  origin?: FactorOrigin;
}

export interface FactorUpdate {
  name?: string;
  hypothesis?: string;
  status?: FactorStatus;
  theme?: string[];
  formula?: string;
}

export interface FactorEvalResult {
  factor: FactorRecord | null;
  metrics: {
    mode?: string;
    ic_stats?: {
      ic_mean?: number | null;
      icir?: number | null;
      ic_pos_ratio?: number | null;
      valid_days?: number;
    };
    gate1_passed?: boolean;
    gate2_passed?: boolean;
    gate3_passed?: boolean;
    gate4_passed?: boolean;
    gate1_detail?: Record<string, unknown>;
    gate2_detail?: Record<string, unknown>;
    gate3_detail?: Record<string, unknown>;
    gate4_note?: string;
    status?: string;
    reject_reason?: string;
  };
  panel?: {
    source?: string;
    n_stocks?: number;
    n_days?: number;
    market?: string | null;
  };
  formula?: string;
}

export interface FactorMineLlmRequest {
  universe?: FactorUniverse;
  rounds?: number;
  k?: number;
  theme_hint?: string;
  use_synthetic?: boolean;
}

export interface FactorMineGpRequest {
  track?: "market" | "cs";
  universe?: FactorUniverse;
  population?: number;
  generations?: number;
  use_synthetic?: boolean;
  lookback?: number;
}

export type FactorSynthMethod = "equal" | "ic" | "ic_ir";

export interface FactorSynthesizeRequest {
  method?: FactorSynthMethod;
  factor_ids: string[];
  id?: string;
  name?: string;
  hypothesis?: string;
  use_synthetic?: boolean;
  replace?: boolean;
}

export interface FactorSynthesizeResult {
  factor: FactorRecord;
  metrics: Record<string, unknown>;
  gate5_passed?: boolean;
  gate5_note?: string;
}

export interface FactorMineRun {
  run_id: string;
  kind?: string;
  status: "running" | "done" | "error" | string;
  round?: number;
  rounds?: number;
  k?: number;
  universe?: FactorUniverse;
  theme_hint?: string;
  use_synthetic?: boolean;
  message?: string;
  funnel?: {
    proposed?: number;
    parse_fail?: number;
    evaled?: number;
    passed?: number;
    rejected?: number;
  };
  accepted_ids?: string[];
  error?: string | null;
  updated_at?: string;
}

export interface FactorScreenPick {
  rank: number;
  symbol: string;
  score: number;
  factor_scores: Record<string, number>;
}

export interface FactorScreenResult {
  status: string;
  as_of: string;
  generated_at: string;
  universe: FactorUniverse;
  method: "equal" | "ic" | "ic_ir";
  factor_ids: string[];
  factors: Array<{
    id: string;
    name: string;
    status: string;
    ic_mean?: number;
    weight?: number;
  }>;
  top_n: number;
  picks: FactorScreenPick[];
  meta: {
    universe?: Record<string, unknown>;
    panel?: Record<string, unknown>;
    screen_universe_size?: number;
    use_synthetic?: boolean;
  };
}

export interface FactorScreenRequest {
  universe?: FactorUniverse;
  factor_ids?: string[];
  method?: "equal" | "ic" | "ic_ir";
  top_n?: number;
  max_factors?: number;
  max_symbols?: number;
  lookback?: number;
  use_synthetic?: boolean;
}

export interface FactorScreenApplyRequest {
  portfolio_id?: string;
  symbols: string[];
  mode?: "merge" | "replace";
}

export interface PromptRecord {
  id: string;
  category: PromptCategory;
  persona: string;
  instructions: string;
  complete: boolean;
  builtin: boolean;
}

export interface PromptCreate {
  id: string;
  category: PromptCategory;
  persona: string;
  instructions: string;
  complete?: boolean;
}

export interface PromptUpdate {
  category?: PromptCategory;
  persona?: string;
  instructions?: string;
  complete?: boolean;
}

export interface AgentRecord {
  id: string;
  name: string;
  model_tier: ModelTier;
  tools: string[];
  prompt_id: string;
  status: AgentStatus;
  builtin: boolean;
}

export interface AgentDetail extends AgentRecord {
  persona: string;
  instructions: string;
}

export interface AgentCreate {
  id: string;
  name: string;
  model_tier: ModelTier;
  tools: string[];
  prompt_id: string;
  status?: AgentStatus;
}

export interface AgentUpdate {
  name?: string;
  model_tier?: ModelTier;
  tools?: string[];
  prompt_id?: string;
  status?: AgentStatus;
}

export interface ToolRecord {
  id: string;
  name: string;
  description: string;
  guidance: string;
}

export const PROMPT_CATEGORIES: { id: PromptCategory; label: string }[] = [
  { id: "agent-persona", label: "人设 persona" },
  { id: "analysis", label: "分析 instructions" },
  { id: "extraction", label: "抽取 extraction" },
  { id: "summary", label: "摘要 summary" },
];
