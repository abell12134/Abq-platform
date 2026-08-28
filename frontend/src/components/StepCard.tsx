import { useEffect, useState } from "react";
import type { AnalysisStep } from "../types/analysis";
import { agentLabel } from "../lib/agentLabels";
import { stepBadge, stepPreview, stepAgentTone } from "../lib/chatDisplaySteps";
import { groupWorkflowSteps } from "../lib/workflowPhases";
import { MarkdownBody } from "./MarkdownBody";
import "../pages/pages.css";

function roleClass(role: AnalysisStep["role"]) {
  if (role === "user") return "r-user";
  if (role === "tool") return "r-tool";
  if (role === "agent") return "r-agent";
  if (role === "compact") return "r-compact";
  return "r-assistant";
}

function roleLabel(role: AnalysisStep["role"]) {
  const map = {
    user: "USER",
    assistant: "ASSISTANT",
    tool: "TOOL",
    agent: "AGENT",
    compact: "COMPACT",
  } as const;
  return map[role];
}

export function StepCard({
  step,
  defaultCollapsed = false,
  streaming = false,
}: {
  step: AnalysisStep;
  defaultCollapsed?: boolean;
  streaming?: boolean;
}) {
  const [open, setOpen] = useState(!defaultCollapsed);

  useEffect(() => {
    if (streaming) setOpen(true);
  }, [streaming]);

  if (step.role === "user") {
    return (
      <div className="col">
        <div className="who">你</div>
        <div className="bubble userBubble">{step.result}</div>
      </div>
    );
  }

  const isTool = step.role === "tool";
  const isJudge = step.agent === "judge";
  const toolCall = step.tool_calls[0];
  const isToolError = toolCall?.status === "error";
  const suggestedAction = toolCall?.suggested_action?.trim() || null;
  const body = step.result || step.thought;
  const preview = stepPreview(step);
  const badge = stepBadge(step);
  const tone = stepAgentTone(step.agent);
  const showMarkdown = step.role === "assistant" && body.length > 0;

  return (
    <div className={["col", isJudge ? "col-judge" : ""].filter(Boolean).join(" ")}>
      <div
        className={[
          "pcard",
          tone,
          open ? "pcard-open" : "pcard-collapsed",
          isTool ? "pcard-tool" : "",
          isToolError ? "pcard-tool-err" : "",
          isJudge ? "pcard-judge" : "",
          streaming ? "pcard-streaming" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <button
          type="button"
          className="phd stepToggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          <span className="stepChevron" aria-hidden>
            {open ? "▾" : "▸"}
          </span>
          <span className="agentChip">{agentLabel(step.agent)}</span>
          {isToolError ? <span className="stepBadge stepBadgeErr">失败</span> : null}
          {badge ? <span className="stepBadge">{badge}</span> : null}
          {!open && suggestedAction ? (
            <span className="stepSuggestedHint">建议：{suggestedAction}</span>
          ) : null}
          {!open ? <span className="stepPreview">{preview}</span> : null}
          {streaming ? <span className="stepStreamDot" aria-label="生成中" /> : null}
          {step.llm && !open ? (
            <span className="stepMeta">{step.llm.model.split(":")[0]}</span>
          ) : null}
        </button>
        {open ? (
          <div className="pbd">
            {step.llm ? (
              <div className="stepLlmMeta">
                {step.llm.tier} · {step.llm.model}
              </div>
            ) : null}
            {showMarkdown ? (
              <MarkdownBody text={body} />
            ) : isTool ? (
              <pre className="stepBody stepBodyMono">{body}</pre>
            ) : (
              <MarkdownBody text={body || "（模型未返回文本）"} />
            )}
            {suggestedAction ? (
              <div className="stepSuggestedAction">
                <span className="stepSuggestedLabel">建议下一步</span>
                <span>{suggestedAction}</span>
              </div>
            ) : null}
            {toolCall?.output_ref ? (
              <div className="kv">ref {toolCall.output_ref}</div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function WorkflowLedger({ steps }: { steps: AnalysisStep[] }) {
  /** @deprecated Use WorkflowPage split layout; kept for tests or embeds */
  const groups = groupWorkflowSteps(steps);
  return (
    <div className="ledger">
      {groups.map((group) => (
        <section className="ledgerPhase" key={group.id}>
          <div className="phaseHd">{group.label}</div>
          {group.steps.map((step) => (
            <div className="erow" key={step.id}>
              <div className={`role ${roleClass(step.role)}`}>
                <div>{agentLabel(step.agent)}</div>
                <div style={{ fontSize: 10, opacity: 0.6 }}>{roleLabel(step.role)}</div>
                {step.llm ? (
                  <div className="tier">
                    {step.llm.tier} · {step.llm.model}
                  </div>
                ) : null}
              </div>
              <div className="ebody">{step.result || step.thought}</div>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
