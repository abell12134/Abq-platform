import type { AnalysisMeta, AnalysisStep, ContextSnapshot } from "../types/analysis";
import { agentLabel } from "./agentLabels";

export function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.max(1, Math.ceil(text.length / 3));
}

function stepBody(step: AnalysisStep): string {
  return (step.result || step.thought || "").trim();
}

function collectOutputRefs(steps: AnalysisStep[]): string[] {
  const refs: string[] = [];
  const seen = new Set<string>();
  for (const step of steps) {
    for (const tc of step.tool_calls) {
      if (tc.output_ref && !seen.has(tc.output_ref)) {
        seen.add(tc.output_ref);
        refs.push(tc.output_ref);
      }
    }
  }
  return refs;
}

function assistantFindings(steps: AnalysisStep[]): string[] {
  const byAgent = new Map<string, AnalysisStep>();
  for (const step of steps) {
    if (step.role !== "assistant") continue;
    const body = stepBody(step);
    if (!body || body === "（模型未返回文本）") continue;
    byAgent.set(step.agent, step);
  }
  return [...byAgent.values()].map((step) => {
    const body = stepBody(step);
    const preview = findingPreview(body, 200);
    return `[${step.id}] ${step.agent}: ${preview}`;
  });
}

/** One-line preview for UI cards */
export function findingPreview(text: string, max = 96): string {
  const line =
    text
      .split(/\r?\n/)
      .map((l) => l.trim())
      .find((l) => l && !l.startsWith("```")) ?? text;
  const plain = line
    .replace(/^#+\s*/, "")
    .replace(/\*\*/g, "")
    .replace(/^[-*]\s*/, "")
    .trim();
  return plain.length > max ? `${plain.slice(0, max)}…` : plain;
}

export interface TokenSegment {
  id: string;
  label: string;
  tokens: number;
  tone: "user" | "tool" | "assistant" | "snapshot" | "runtime";
}

export interface ContextViewModel {
  hasPath: boolean;
  persistedSteps: number;
  persistedTokens: number;
  persistedSegments: TokenSegment[];
  modelTokens: number;
  modelSegments: TokenSegment[];
  savingsPct: number;
  carriedOutputs: string[];
  keyFindings: { step_id: string; agent: string; text: string }[];
  summary: string;
  runtimePreview: string;
  compactionEvents: ContextSnapshot[];
  projectionSource: "snapshot" | "live" | "empty";
}

export function buildRuntimePreview(
  meta: AnalysisMeta,
  snapshot: Pick<ContextViewModel, "summary" | "keyFindings" | "carriedOutputs">,
  task = "（下一 agent 任务由编排注入）",
): string {
  const focus = meta.focus?.trim() || "（无侧重，按标准链路）";
  const symbol = meta.target ?? "（未指定）";
  const findingsBlock =
    snapshot.keyFindings.length > 0
      ? snapshot.keyFindings
          .map((f) => `- [${f.step_id}] ${agentLabel(f.agent)}: ${f.text}`)
          .join("\n")
      : "- （尚无，这是第一步）";
  const carried =
    snapshot.carriedOutputs.length > 0 ? snapshot.carriedOutputs.join(", ") : "（无）";

  return `## 本轮分析上下文
- 分析种类: ${meta.kind}
- 市场: ${meta.realm}
- 标的: ${symbol}
- 用户侧重: ${focus}

## 已压缩的历史（ContextSnapshot）
- 摘要: ${snapshot.summary || "（尚无，这是第一步）"}
- 关键发现:
${findingsBlock}
- 仍携带的原始输出: ${carried}

## 本步任务
${task}`;
}

export function buildContextView(
  steps: AnalysisStep[],
  snapshots: ContextSnapshot[],
  meta: AnalysisMeta,
): ContextViewModel {
  if (!steps.length) {
    return {
      hasPath: false,
      persistedSteps: 0,
      persistedTokens: 0,
      persistedSegments: [],
      modelTokens: 0,
      modelSegments: [],
      savingsPct: 0,
      carriedOutputs: [],
      keyFindings: [],
      summary: "",
      runtimePreview: "",
      compactionEvents: [],
      projectionSource: "empty",
    };
  }

  const byRole = { user: 0, tool: 0, assistant: 0 };
  for (const step of steps) {
    const t = estimateTokens(stepBody(step));
    if (step.role === "user") byRole.user += t;
    else if (step.role === "tool") byRole.tool += t;
    else if (step.role === "assistant") byRole.assistant += t;
  }

  const persistedTokens = byRole.user + byRole.tool + byRole.assistant;
  const persistedSegments: TokenSegment[] = [
    { id: "user", label: "用户消息", tokens: byRole.user, tone: "user" as const },
    { id: "tool", label: "工具输出（全量落盘）", tokens: byRole.tool, tone: "tool" as const },
    { id: "assistant", label: "Agent 结论", tokens: byRole.assistant, tone: "assistant" as const },
  ].filter((s) => s.tokens > 0);

  const latestSnapshot = snapshots[snapshots.length - 1];
  const liveFindings = assistantFindings(steps);
  const liveRefs = collectOutputRefs(steps);

  const projectionSource: ContextViewModel["projectionSource"] = latestSnapshot
    ? "snapshot"
    : liveFindings.length
      ? "live"
      : "empty";

  const summary =
    latestSnapshot?.summary ??
    (liveFindings.length
      ? `共 ${steps.length} 步尚未触发压缩；研判前将用 findings 直喂（${liveFindings.length} 条）。`
      : "（尚无压缩快照）");

  const keyFindings =
    latestSnapshot?.key_findings ??
    liveFindings.slice(-8).map((line) => {
      const m = line.match(/^\[([^\]]+)\]\s*([^:]+):\s*(.+)$/);
      return m
        ? { step_id: m[1]!, agent: m[2]!.trim(), text: m[3]!.trim() }
        : { step_id: "", agent: "finding", text: line };
    });

  const carriedOutputs = latestSnapshot?.carried_outputs ?? liveRefs;

  const runtimePreview = buildRuntimePreview(meta, { summary, keyFindings, carriedOutputs });
  const runtimeTokens = estimateTokens(runtimePreview);

  const findingsText = keyFindings.map((f) => f.text).join("\n");
  const findingsTokens = estimateTokens(findingsText);
  const carriedTokens = estimateTokens(carriedOutputs.join(", "));

  const modelSegments: TokenSegment[] = [
    {
      id: "runtime",
      label: "Runtime user turn",
      tokens: runtimeTokens,
      tone: "runtime" as const,
    },
    {
      id: "findings",
      label: "关键发现（提携）",
      tokens: findingsTokens,
      tone: "snapshot" as const,
    },
    {
      id: "refs",
      label: "carried outputRef",
      tokens: carriedTokens,
      tone: "tool" as const,
    },
  ].filter((s) => s.tokens > 0);

  const modelTokens = modelSegments.reduce((n, s) => n + s.tokens, 0);
  const rawForSavings = latestSnapshot?.total_raw_tokens ?? persistedTokens;
  const compressedForSavings = latestSnapshot?.total_compressed_tokens ?? modelTokens;
  const savingsPct =
    rawForSavings > 0
      ? Math.round(((rawForSavings - compressedForSavings) / rawForSavings) * 100)
      : 0;

  return {
    hasPath: true,
    persistedSteps: steps.length,
    persistedTokens,
    persistedSegments,
    modelTokens,
    modelSegments,
    savingsPct: Math.max(0, savingsPct),
    carriedOutputs,
    keyFindings,
    summary,
    runtimePreview,
    compactionEvents: snapshots,
    projectionSource,
  };
}
