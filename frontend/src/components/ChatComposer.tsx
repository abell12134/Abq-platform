import type { LlmHealthTier, LlmProviderInfo } from "../types/analysis";
import { MemoryHintBanner } from "./MemoryHintBanner";
import "./ChatComposer.css";

interface ChatComposerProps {
  input: string;
  focus: string;
  routeHint: string | null;
  memoryHints: string[];
  memorySummary: string | null;
  memoryLoading: boolean;
  streaming: boolean;
  pipelinePhase: string | null;
  messagesCount: number;
  stepsCount: number;
  activePathId: string | null;
  primaryOverride: string | null;
  primaryProviders: LlmProviderInfo[];
  activePrimary: LlmProviderInfo | undefined;
  local: LlmHealthTier | undefined;
  onInputChange: (v: string) => void;
  onFocusChange: (v: string) => void;
  onPrimaryChange: (v: string | null) => void;
  onSend: () => void;
  onCancel: () => void;
  onNewChat: () => void;
}

export function ChatComposer({
  input,
  focus,
  routeHint,
  memoryHints,
  memorySummary,
  memoryLoading,
  streaming,
  pipelinePhase,
  messagesCount,
  stepsCount,
  activePathId,
  primaryOverride,
  primaryProviders,
  activePrimary,
  local,
  onInputChange,
  onFocusChange,
  onPrimaryChange,
  onSend,
  onCancel,
  onNewChat,
}: ChatComposerProps) {
  return (
    <div className="chatDock">
      <MemoryHintBanner hints={memoryHints} summary={memorySummary} loading={memoryLoading} />
      {routeHint ? <div className="routeHint">{routeHint}</div> : null}
      <div className="composer">
        <input
          className="focusIn"
          value={focus}
          onChange={(e) => onFocusChange(e.target.value)}
          placeholder="侧重（可选），如：重点看量价背离"
        />
        <textarea
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder="描述你想分析的内容…"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
        />
        <div className="cbar">
          <select
            className="dd"
            value={primaryOverride ?? (activePrimary ? `${activePrimary.id}:${activePrimary.model}` : "")}
            onChange={(e) => onPrimaryChange(e.target.value || null)}
          >
            {primaryProviders.map((p) => (
              <option key={`${p.id}:${p.model}`} value={`${p.id}:${p.model}`}>
                主模型 · {p.label}
              </option>
            ))}
          </select>
          <button type="button" className="dd mutedDd">
            本地 · {local?.model?.split(":")[0] ?? "nemotron"}
          </button>
          <button
            type="button"
            className="send"
            disabled={streaming || !input.trim()}
            onClick={onSend}
          >
            ↑
          </button>
          {streaming ? (
            <button type="button" className="stopBtn" title="停止分析" onClick={onCancel}>
              ■
            </button>
          ) : null}
        </div>
      </div>
      <div className="metrics">
        <span>
          {messagesCount} 条 · {stepsCount} 步
          {activePathId ? ` · ${activePathId.slice(0, 8)}` : ""}
          {streaming
            ? ` · ${pipelinePhase ?? "分析中"}`
            : activePathId
              ? " · 续聊基于已有报告"
              : ""}
        </span>
        <button type="button" className="metricsBtn" onClick={onNewChat}>
          新对话
        </button>
      </div>
    </div>
  );
}
