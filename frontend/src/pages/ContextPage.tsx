import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { fetchPath } from "../api/client";
import { agentLabel } from "../lib/agentLabels";
import { ContextMemoryPanel } from "../components/ContextMemoryPanel";
import { QueryErrorBanner } from "../components/QueryErrorBanner";
import { buildContextView, findingPreview } from "../lib/contextView";
import { useUiStore } from "../stores/ui";
import "./pages.css";

function TokenStack({
  segments,
  total,
  compact = false,
}: {
  segments: { id: string; label: string; tokens: number; tone: string }[];
  total: number;
  compact?: boolean;
}) {
  if (!total) return <div className="ctxEmptyBar">暂无</div>;
  return (
    <div className={`ctxTokenStack ${compact ? "ctxTokenStackCompact" : ""}`}>
      <div className="ctxTokenBar">
        {segments.map((seg) => (
          <div
            key={seg.id}
            className={`ctxTokenSeg tone-${seg.tone}`}
            style={{ width: `${Math.max(4, (seg.tokens / total) * 100)}%` }}
            title={`${seg.label}: ${seg.tokens.toLocaleString()}`}
          />
        ))}
      </div>
      {!compact ? (
        <ul className="ctxSegLegend">
          {segments.map((seg) => (
            <li key={seg.id}>
              <span className={`ctxDot tone-${seg.tone}`} />
              {seg.label}
              <span className="ctxSegVal">{seg.tokens.toLocaleString()}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function FindingCard({
  stepId,
  agent,
  text,
}: {
  stepId: string;
  agent: string;
  text: string;
}) {
  const [open, setOpen] = useState(false);
  const preview = findingPreview(text, 88);

  return (
    <div className={`ctxFindingCard tone-${agent}`}>
      <button type="button" className="ctxFindingHd" onClick={() => setOpen((v) => !v)}>
        <span className="ctxFindingAgent">{agentLabel(agent)}</span>
        <span className="ctxFindingPreview">{preview}</span>
        <span className="ctxFindingChevron">{open ? "▾" : "▸"}</span>
      </button>
      {open ? (
        <div className="ctxFindingBody">
          <div className="ctxFindingMeta">step {stepId}</div>
          <pre className="ctxFindingText">{text}</pre>
        </div>
      ) : null}
    </div>
  );
}

export function ContextPage() {
  const meta = useUiStore((s) => s.analysisMeta);
  const pathId = useUiStore((s) => s.pathId);
  const steps = useUiStore((s) => s.workflowSteps);
  const snapshots = useUiStore((s) => s.contextSnapshots);
  const setSnapshots = useUiStore((s) => s.setContextSnapshots);

  const {
    data: pathDoc,
    isError: pathError,
    error: pathErr,
  } = useQuery({
    queryKey: ["path-context", pathId],
    queryFn: () => fetchPath(pathId!),
    enabled: Boolean(pathId),
  });

  useEffect(() => {
    if (pathDoc?.snapshots?.length) setSnapshots(pathDoc.snapshots);
  }, [pathDoc?.snapshots, setSnapshots]);

  const mergedSnapshots = pathDoc?.snapshots?.length ? pathDoc.snapshots : snapshots;

  const view = useMemo(
    () => buildContextView(steps, mergedSnapshots, meta),
    [steps, mergedSnapshots, meta],
  );

  if (!view.hasPath) {
    return (
      <div className="pad ctxPage">
        <h1>上下文</h1>
        <p className="sub">对比持久化全量与模型可见投影：token 构成、压缩事件、runtime 预览。</p>
        <div className="ctxHeroCards">
          <div className="ctxHeroCard">
            <h3>持久化层</h3>
            <p>工作流全量 steps，供回放。</p>
          </div>
          <div className="ctxHeroCard">
            <h3>LLM 投影层</h3>
            <p>压缩后的 ContextSnapshot + runtime user turn。</p>
          </div>
          <div className="ctxHeroCard">
            <h3>压缩事件</h3>
            <p>续聊超阈值时 local 模型摘要。</p>
          </div>
        </div>
      </div>
    );
  }

  const compressed = view.projectionSource === "snapshot";

  return (
    <div className="pad ctxPage">
      <header className="ctxHd">
        <div>
          <h1>上下文</h1>
          <p className="sub ctxHdSub">
            {view.persistedSteps} 步落盘 ·{" "}
            {compressed ? "已压缩注入" : "未压缩，findings 直喂 judge"}
          </p>
        </div>
        <div className="ctxMetaPills">
          <span className="ctxPill">{meta.target ?? "—"}</span>
          <span className={`ctxPill ${compressed ? "ctxPillOk" : ""}`}>
            {compressed ? "已压缩" : "未达阈值"}
          </span>
        </div>
      </header>

      <QueryErrorBanner isError={pathError} error={pathErr} label="会话上下文加载失败" />

      <section className="ctxMetricsRow" aria-label="Token 对比">
        <article className="ctxMetricCard">
          <span className="ctxMetricLabel">持久化全量</span>
          <span className="ctxMetricValue">{view.persistedTokens.toLocaleString()}</span>
          <span className="ctxMetricHint">tokens · {view.persistedSteps} 步</span>
          <TokenStack segments={view.persistedSegments} total={view.persistedTokens} compact />
        </article>
        <article className="ctxMetricCard ctxMetricCardAccent">
          <span className="ctxMetricLabel">模型可见</span>
          <span className="ctxMetricValue">{view.modelTokens.toLocaleString()}</span>
          <span className="ctxMetricHint">
            {compressed ? "快照投影" : "runtime 直投"}
          </span>
          <TokenStack segments={view.modelSegments} total={view.modelTokens} compact />
        </article>
        <article className="ctxMetricCard">
          <span className="ctxMetricLabel">压缩率</span>
          <span className="ctxMetricValue ctxMetricSave">
            {view.savingsPct > 0 ? `${view.savingsPct}%` : "—"}
          </span>
          <span className="ctxMetricHint">
            {view.savingsPct > 0 ? "相对持久化层" : "未触发压缩"}
          </span>
        </article>
        <article className="ctxMetricCard">
          <span className="ctxMetricLabel">关键发现</span>
          <span className="ctxMetricValue">{view.keyFindings.length}</span>
          <span className="ctxMetricHint">提携进下一 agent</span>
        </article>
      </section>

      <div className="ctxBodyGrid">
        <div className="ctxSideCol">
          <section className="ctxBlock ctxBlockFlush">
            <h2>快照摘要</h2>
            <p className="ctxSummaryLine">{view.summary}</p>
            {view.carriedOutputs.length > 0 ? (
              <div className="ctxRefRow">
                <span className="ctxRefLabel">outputRef</span>
                <div className="ctxRefChips">
                  {view.carriedOutputs.map((ref) => (
                    <span className="ctxRefChip" key={ref}>
                      {ref}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </section>

          <ContextMemoryPanel />

          <section className="ctxBlock ctxBlockFlush">
            <div className="ctxBlockHd">
              <h2>压缩事件</h2>
              <span className="ctxLocalBadge">local</span>
            </div>
            {view.compactionEvents.length === 0 ? (
              <p className="ctxMutedLine">未触发 · 续聊步骤增多后自动压缩</p>
            ) : (
              <ul className="ctxEventList">
                {view.compactionEvents.map((ev, i) => (
                  <li className="ctxEventItem" key={i}>
                    <span className="ctxEventTokens">
                      {ev.total_raw_tokens.toLocaleString()} →{" "}
                      {ev.total_compressed_tokens.toLocaleString()}
                    </span>
                    <p className="ctxEventSummary">{findingPreview(ev.summary, 120)}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <details className="ctxBlock ctxDetails">
            <summary className="ctxDetailsSum">
              <span>Runtime user turn</span>
              <span className="ctxMutedLine">build_user_turn</span>
            </summary>
            <pre className="ctxRuntimePreview">{view.runtimePreview}</pre>
          </details>
        </div>

        <div className="ctxMainCol">
          {view.keyFindings.length > 0 ? (
            <section className="ctxBlock ctxBlockFill">
              <div className="ctxBlockHd">
                <h2>关键发现</h2>
                <span className="ctxMutedLine">点击展开全文</span>
              </div>
              <div className="ctxFindingGrid">
                {view.keyFindings.map((f) => (
                  <FindingCard
                    key={`${f.step_id}-${f.agent}`}
                    stepId={f.step_id}
                    agent={f.agent}
                    text={f.text}
                  />
                ))}
              </div>
            </section>
          ) : (
            <section className="ctxBlock ctxBlockFill ctxEmptyFindings">
              <h2>关键发现</h2>
              <p className="ctxMutedLine">分析进行中，agent 结论将出现在此处。</p>
            </section>
          )}

          {view.persistedSegments.length > 0 ? (
            <section className="ctxBlock ctxBlockFlush">
              <h2>持久化 token 构成</h2>
              <TokenStack
                segments={view.persistedSegments}
                total={view.persistedTokens}
              />
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
