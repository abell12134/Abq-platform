import { useEffect, useState } from "react";
import { useUiStore } from "../stores/ui";
import "./AppShellHeader.css";

const KIND_LABEL: Record<string, string> = {
  single: "单票 · A股",
  market: "大盘 · A股",
  portfolio: "选组 · A股",
};

interface AppShellHeaderProps {
  sessionTitle: string;
  kind: string | null | undefined;
  target: string | null | undefined;
  focus: string | null | undefined;
  showInsightPanel: boolean;
  insightPanelOpen: boolean;
  onToggleInsightPanel: () => void;
  primaryLabel: string;
  localLabel: string;
  llmOk: boolean;
  localOk: boolean;
  llmHealthError: boolean;
}

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Asia/Shanghai",
  });
}

export function AppShellHeader({
  sessionTitle,
  kind,
  target,
  focus,
  showInsightPanel,
  insightPanelOpen,
  onToggleInsightPanel,
  primaryLabel,
  localLabel,
  llmOk,
  localOk,
  llmHealthError,
}: AppShellHeaderProps) {
  const streaming = useUiStore((s) => s.streaming);
  const clock = useClock();

  return (
    <header className="top">
      <div className="topBrandMark" aria-hidden>
        ABQ//
      </div>
      <div className="topMain">
        <div className="sessTitle" title={sessionTitle}>
          {sessionTitle}
        </div>
        <div className="mode">
          {target ? `${target} · ` : ""}
          {KIND_LABEL[kind ?? "single"] ?? kind}
          {focus ? ` · 侧重 ${focus.slice(0, 16)}` : ""}
        </div>
      </div>
      {showInsightPanel ? (
        <button type="button" className="panelToggle" onClick={onToggleInsightPanel}>
          {insightPanelOpen ? "收起摘要" : "展开摘要"}
        </button>
      ) : null}
      <div className="topR">
        <span className={`feedStatus ${streaming ? "live" : ""}`}>
          <span className={`liveDot ${streaming ? "on" : ""}`} />
          {streaming ? "LIVE" : "快照"}
        </span>
        <time className="topClock" dateTime={clock}>
          {clock}
        </time>
        <span
          className={`llmPill ${llmOk ? "ok" : ""}`}
          title={llmHealthError ? "LLM 健康检查失败" : undefined}
        >
          主 · {primaryLabel}
        </span>
        <span className={`llmPill ${localOk ? "ok" : ""}`}>本地 · {localLabel}</span>
      </div>
    </header>
  );
}
