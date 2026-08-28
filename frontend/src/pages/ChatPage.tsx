import { useMemo } from "react";
import { ScreenActionCard, parseApplyResult, parseScreenResult } from "../components/ScreenActionCard";
import { StepCard } from "../components/StepCard";
import { ToolGroupCard } from "../components/ToolGroupCard";
import { CompactionBanner } from "./SingleTicketPage";
import { buildChatThread, stepDefaultCollapsed } from "../lib/chatDisplaySteps";
import { useChatAutoScroll } from "../hooks/useChatAutoScroll";
import { useUiStore } from "../stores/ui";
import { useAnalyzeStream } from "../hooks/useAnalyzeStream";
import "./pages.css";

export function ChatPage() {
  const workflowSteps = useUiStore((s) => s.workflowSteps);
  const streaming = useUiStore((s) => s.streaming);
  const streamActiveIds = useUiStore((s) => s.streamActiveIds);
  const streamError = useUiStore((s) => s.streamError);
  const pipelinePhase = useUiStore((s) => s.pipelinePhase);
  const activePathId = useUiStore((s) => s.activePathId);
  const setPage = useUiStore((s) => s.setPage);
  const setActivePortfolioId = useUiStore((s) => s.setActivePortfolioId);
  const { start } = useAnalyzeStream();
  const threadItems = useMemo(() => buildChatThread(workflowSteps), [workflowSteps]);
  const hasMessages = threadItems.length > 0;
  const scrollKey = useMemo(() => {
    let size = workflowSteps.length;
    for (const step of workflowSteps) {
      size += (step.result?.length ?? 0) + (step.thought?.length ?? 0);
    }
    size += Object.keys(streamActiveIds).length;
    return size;
  }, [workflowSteps, streamActiveIds]);
  const msgsRef = useChatAutoScroll(hasMessages, scrollKey);

  return (
    <div className="thread">
      {!hasMessages ? (
        <div className="hero">
          <p className="heroKicker">ABQ//Lab · 编排分析工作台</p>
          <h1>用自然语言发起 A股 / ETF 分析</h1>
          <p className="sub">
            描述你想看的票、板块或组合。平台用 LLM 编排取数、清洗、多 agent 研判，全过程可回放、可压缩。
          </p>
          <div className="heroHints">
            <p className="heroHintLabel">Command</p>
            <ul className="heroExamples">
              <li>看 600519，最近量价如何</li>
              <li>用因子从沪深300选出 20 只股票</li>
              <li>从沪深300用因子选出 20 只，放进默认自选并诊断</li>
              <li>列出我的自选组合</li>
              <li>有哪些动量因子</li>
              <li>上次怎么看茅台</li>
            </ul>
          </div>
          <p className="sub heroFoot">
            首次调用 qlib 数据会解压 `data/qib/qlib_bin.tar.gz`（约 1 分钟），之后走本地缓存。
          </p>
        </div>
      ) : (
        <div className="msgs" ref={msgsRef}>
          <CompactionBanner />
          {threadItems.map((item) => {
            if (item.kind === "tool-group") {
              return (
                <ToolGroupCard
                  key={item.id}
                  steps={item.steps}
                  symbol={item.symbol}
                  defaultCollapsed
                />
              );
            }
            if (item.step.role === "tool" && item.step.agent === "run_factor_screen") {
              const screen = parseScreenResult(item.step.result);
              if (screen) {
                return (
                  <div key={item.step.id} className="col">
                    <ScreenActionCard
                      result={screen}
                      onDiagnose={(portfolioId) => {
                        setActivePortfolioId(portfolioId);
                        setPage("chat");
                        void start({
                          message: `帮我诊断组合 ${portfolioId}`,
                          session_id: activePathId,
                          kind: "portfolio",
                          realm: "a-share",
                          target: portfolioId,
                        });
                      }}
                    />
                  </div>
                );
              }
            }
            if (item.step.role === "tool" && item.step.agent === "apply_screen_to_portfolio") {
              const applied = parseApplyResult(item.step.result);
              if (applied?.portfolio_id) {
                return (
                  <div key={item.step.id} className="col">
                    <div className="bubble" style={{ maxWidth: 560 }}>
                      已导入选组「{applied.name ?? applied.portfolio_id}」（{applied.member_count ?? "—"} 只）
                    </div>
                  </div>
                );
              }
            }
            return (
              <StepCard
                key={item.step.id}
                step={item.step}
                defaultCollapsed={stepDefaultCollapsed(item.step, streamActiveIds)}
                streaming={Boolean(streamActiveIds[item.step.id])}
              />
            );
          })}
          {streaming && Object.keys(streamActiveIds).length === 0 ? (
            <div className="col">
              <div className="bubble" style={{ color: "var(--faint)" }}>
                {pipelinePhase ? `编排中…（${pipelinePhase}）` : "编排中…（取数 / 工具调用阶段）"}
              </div>
            </div>
          ) : null}
          {streamError ? (
            <div className="col">
              <div className="bubble" style={{ color: "#e88", borderColor: "#633" }}>
                {streamError}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
