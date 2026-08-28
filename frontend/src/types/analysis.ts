export type PageId = "chat" | "portfolio" | "workflow" | "context" | "agent-lib" | "ticket";
export type PathStatus = "running" | "done" | "error";
export type ModelTier = "primary" | "local";
export type AgentStatus = "active" | "draft";

export interface LlmRef {
  tier: ModelTier;
  provider: string;
  model: string;
}

export interface ToolCall {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  output?: string | null;
  output_ref?: string | null;
  status: "ok" | "error" | "running";
  suggested_action?: string | null;
}

export interface AnalysisStep {
  id: string;
  agent: string;
  role: "user" | "assistant" | "tool" | "agent" | "compact";
  thought: string;
  result: string;
  tool_calls: ToolCall[];
  llm?: LlmRef | null;
  ts: string;
}

export interface AnalyzeRequest {
  message: string;
  session_id?: string | null;
  kind?: "market" | "single" | "portfolio";
  realm?: "a-share" | "etf";
  target?: string | null;
  focus?: string | null;
  agent_ids?: string[] | null;
  prompt_id?: string | null;
  primary_model?: string | null;
  enable_debate?: boolean;
  debate_rounds?: number;
  force_full?: boolean;
}

export interface ComposeRouteResult {
  kind: string;
  target: string | null;
  agent_ids: string[];
  prompt_id: string | null;
  enable_debate: boolean | null;
  rationale: string;
  memory_intent?: boolean;
}

export interface MemoryPreviewResult {
  status: string;
  memory_intent: boolean;
  symbol: string | null;
  hints: string[];
  summary: string;
}

export interface ContextSnapshot {
  summary: string;
  key_findings: { step_id: string; agent: string; text: string }[];
  carried_outputs: string[];
  total_raw_tokens: number;
  total_compressed_tokens: number;
}

export interface SseEvent {
  type: "step" | "token" | "compaction" | "phase" | "error" | "done" | "memory";
  step?: AnalysisStep;
  path_id?: string;
  step_id?: string;
  agent?: string;
  delta?: string;
  phase?: string;
  label?: string;
  snapshot?: ContextSnapshot;
  message?: string;
}

export interface PathIndexEntry {
  id: string;
  title: string;
  kind: string;
  realm: string;
  status: PathStatus;
  created: string;
  updated: string;
  target?: string | null;
  focus?: string | null;
  judge_stance?: string | null;
  judge_one_liner?: string | null;
  symbols?: string[];
}

export interface LlmHealthTier {
  ok: boolean;
  status: string;
  provider: string;
  model: string;
  label: string;
}

export interface LlmProviderInfo {
  id: string;
  tier: ModelTier;
  label: string;
  model: string;
  base_url: string;
}

export interface AgentSummary {
  id: string;
  name: string;
  model_tier: ModelTier;
  tools: string[];
  prompt_id: string;
  status?: AgentStatus;
  builtin?: boolean;
}

export interface ChatMessage {
  id: string;
  kind: "user" | "step";
  text?: string;
  step?: AnalysisStep;
}

export interface AnalysisMeta {
  kind: AnalyzeRequest["kind"];
  realm: AnalyzeRequest["realm"];
  focus: string | null;
  target: string | null;
  agent_ids?: string[] | null;
  prompt_id?: string | null;
  enable_debate?: boolean | null;
  route_rationale?: string | null;
}
