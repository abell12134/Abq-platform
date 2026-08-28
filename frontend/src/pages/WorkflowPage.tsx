import { useEffect, useMemo, useState } from "react";
import { MarkdownBody } from "../components/MarkdownBody";
import { agentLabel } from "../lib/agentLabels";
import { stepPreview } from "../lib/chatDisplaySteps";
import { groupWorkflowSteps, type WorkflowPhaseGroup } from "../lib/workflowPhases";
import type { AnalysisStep } from "../types/analysis";
import { useUiStore } from "../stores/ui";
import "./WorkflowPage.css";

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

function roleTone(role: AnalysisStep["role"]) {
  if (role === "user") return "user";
  if (role === "tool") return "tool";
  if (role === "agent") return "agent";
  if (role === "compact") return "compact";
  return "assistant";
}

function WorkflowStepRow({
  step,
  index,
  active,
  onSelect,
}: {
  step: AnalysisStep;
  index: number;
  active: boolean;
  onSelect: () => void;
}) {
  const tone = roleTone(step.role);
  return (
    <button
      type="button"
      className={`wfRow ${active ? "active" : ""}`}
      onClick={onSelect}
    >
      <span className={`wfRole wfRole-${tone}`}>{roleLabel(step.role)}</span>
      <span className="wfRowAgent">{agentLabel(step.agent)}</span>
      <span className="wfRowPreview" title={step.result || step.thought}>
        {stepPreview(step)}
      </span>
      <span className="wfRowIdx">#{index + 1}</span>
    </button>
  );
}

function WorkflowPhaseSection({
  group,
  selectedId,
  stepIndexById,
  onSelect,
}: {
  group: WorkflowPhaseGroup;
  selectedId: string | null;
  stepIndexById: Map<string, number>;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="wfPhase">
      <div className="wfPhaseHd">
        {group.label}
        {group.parallel ? <span className="wfParallelBadge">并行</span> : null}
      </div>
      {group.parallel && group.lanes?.length ? (
        <div className="wfParallelGrid">
          {group.lanes.map((lane) => (
            <div className="wfLane" key={lane.id}>
              <div className="wfLaneHd">{lane.label}</div>
              {lane.steps.map((step) => (
                <WorkflowStepRow
                  key={step.id}
                  step={step}
                  index={stepIndexById.get(step.id) ?? 0}
                  active={step.id === selectedId}
                  onSelect={() => onSelect(step.id)}
                />
              ))}
            </div>
          ))}
        </div>
      ) : (
        group.steps.map((step) => (
          <WorkflowStepRow
            key={step.id}
            step={step}
            index={stepIndexById.get(step.id) ?? 0}
            active={step.id === selectedId}
            onSelect={() => onSelect(step.id)}
          />
        ))
      )}
    </section>
  );
}
function WorkflowDetail({ step, index }: { step: AnalysisStep | null; index: number }) {
  if (!step) {
    return (
      <aside className="wfDetail">
        <div className="wfDetailEmpty">选择左侧一步查看详情</div>
      </aside>
    );
  }

  const tone = roleTone(step.role);
  const body = step.result || step.thought || "（无内容）";
  const isTool = step.role === "tool";
  const showMarkdown = step.role === "assistant" && body.length > 0;

  return (
    <aside className="wfDetail">
      <header className="wfDetailHd">
        <div>
          <h2>
            Step {index + 1} · {agentLabel(step.agent)}
          </h2>
          <div className="wfDetailMeta">{step.id}</div>
        </div>
        <span className={`wfDetailRole wfRole-${tone}`}>{roleLabel(step.role)}</span>
      </header>
      <div className="wfDetailScroll">
        <section className="wfDetailSection">
          <h3>摘要</h3>
          <p className="wfDetailSummary">{stepPreview(step)}</p>
        </section>

        <section className="wfDetailSection">
          <h3>{isTool ? "工具输出" : "正文"}</h3>
          {showMarkdown ? (
            <MarkdownBody text={body} />
          ) : (
            <pre className="wfDetailPre">{body}</pre>
          )}
        </section>

        {(step.llm || step.tool_calls.length > 0 || step.ts) && (
          <section className="wfDetailSection">
            <h3>元数据</h3>
            <dl className="wfDetailKv">
              {step.llm ? (
                <>
                  <div className="wfDetailKvRow">
                    <dt>模型</dt>
                    <dd>
                      {step.llm.tier} · {step.llm.model}
                    </dd>
                  </div>
                </>
              ) : null}
              {step.tool_calls.map((tc) => (
                <div className="wfDetailKvRow" key={tc.id}>
                  <dt>工具</dt>
                  <dd>
                    {tc.tool}
                    {tc.output_ref ? ` · ref ${tc.output_ref}` : ""}
                    {tc.status ? ` · ${tc.status}` : ""}
                  </dd>
                </div>
              ))}
              {step.ts ? (
                <div className="wfDetailKvRow">
                  <dt>时间</dt>
                  <dd>{step.ts}</dd>
                </div>
              ) : null}
            </dl>
          </section>
        )}
      </div>
    </aside>
  );
}

export function WorkflowPage() {
  const steps = useUiStore((s) => s.workflowSteps);
  const streaming = useUiStore((s) => s.streaming);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const groups = useMemo(() => groupWorkflowSteps(steps), [steps]);

  const flatSteps = useMemo(() => {
    const out: AnalysisStep[] = [];
    for (const g of groups) {
      if (g.parallel && g.lanes?.length) {
        for (const lane of g.lanes) out.push(...lane.steps);
      } else {
        out.push(...g.steps);
      }
    }
    return out;
  }, [groups]);

  const roleCounts = useMemo(() => {
    const c = { user: 0, tool: 0, assistant: 0, other: 0 };
    for (const s of steps) {
      if (s.role === "user") c.user += 1;
      else if (s.role === "tool") c.tool += 1;
      else if (s.role === "assistant") c.assistant += 1;
      else c.other += 1;
    }
    return c;
  }, [steps]);

  useEffect(() => {
    if (!flatSteps.length) {
      setSelectedId(null);
      return;
    }
    const exists = selectedId && flatSteps.some((s) => s.id === selectedId);
    if (!exists) {
      setSelectedId(flatSteps[flatSteps.length - 1]!.id);
    }
  }, [flatSteps, selectedId]);

  useEffect(() => {
    if (!streaming || !flatSteps.length) return;
    setSelectedId(flatSteps[flatSteps.length - 1]!.id);
  }, [streaming, flatSteps.length, flatSteps[flatSteps.length - 1]?.id]);

  const selectedIndex = flatSteps.findIndex((s) => s.id === selectedId);
  const selectedStep = selectedIndex >= 0 ? flatSteps[selectedIndex]! : null;

  const stepIndexById = useMemo(() => {
    const m = new Map<string, number>();
    flatSteps.forEach((s, i) => m.set(s.id, i));
    return m;
  }, [flatSteps]);

  if (!steps.length) {
    return (
      <div className="wfPage">
        <header className="wfHead">
          <div>
            <h1>工作流</h1>
            <p className="sub wfHeadSub">事件账本 · 全量步骤回放</p>
          </div>
        </header>
        <div className="wfEmpty">
          <p className="sub">先在对话页发起分析，步骤会出现在这里。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="wfPage">
      <header className="wfHead">
        <div>
          <h1>工作流</h1>
          <p className="sub wfHeadSub">事件账本 · 按阶段分组 · 点击步骤查看详情</p>
        </div>
        <div className="wfStats">
          <span className={`wfStat ${streaming ? "run" : ""}`}>
            {streaming ? "进行中" : "已完成"} · {steps.length} 步
          </span>
          <span className="wfStat">ASSISTANT {roleCounts.assistant}</span>
          <span className="wfStat">TOOL {roleCounts.tool}</span>
          {roleCounts.user > 0 ? <span className="wfStat">USER {roleCounts.user}</span> : null}
        </div>
      </header>

      <div className="wfTimelineWrap">
        <div className="wfTimelineLabel">
          <span>轨迹</span>
          <span>{flatSteps.length} events</span>
        </div>
        <div className="wfTimeline" role="tablist" aria-label="步骤轨迹">
          {flatSteps.map((step, i) => (
            <button
              key={step.id}
              type="button"
              className={`wfTimelineSeg tone-${roleTone(step.role)} ${step.id === selectedId ? "active" : ""}`}
              title={`#${i + 1} ${agentLabel(step.agent)}`}
              onClick={() => setSelectedId(step.id)}
            />
          ))}
        </div>
      </div>

      <div className="wfBody">
        <div className="wfList">
          {groups.map((group) => (
            <WorkflowPhaseSection
              key={group.id}
              group={group}
              selectedId={selectedId}
              stepIndexById={stepIndexById}
              onSelect={setSelectedId}
            />
          ))}
        </div>
        <WorkflowDetail step={selectedStep} index={selectedIndex} />
      </div>
    </div>
  );
}
