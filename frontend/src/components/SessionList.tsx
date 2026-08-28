import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { cancelAnalysis, deletePath, fetchPath, fetchPaths } from "../api/client";
import { pathKindBadge } from "../lib/portfolioView";
import { useUiStore } from "../stores/ui";
import type { PathIndexEntry } from "../types/analysis";
import "./SessionList.css";

function statusDot(status: PathIndexEntry["status"]) {
  if (status === "running") return "run";
  if (status === "error") return "err";
  return "ok";
}

function statusLabel(p: PathIndexEntry) {
  if (p.status === "running") return "进行中";
  if (p.status === "error") return "已中断";
  if (p.status === "done") return "已完成";
  return p.kind;
}

function formatWhen(iso: string) {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 3600_000) return "刚才";
    if (diff < 86400_000) return "今天";
    return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
  } catch {
    return "";
  }
}

export function SessionList() {
  const queryClient = useQueryClient();
  const activePathId = useUiStore((s) => s.activePathId);
  const loadPath = useUiStore((s) => s.loadPath);
  const clearThread = useUiStore((s) => s.clearThread);
  const streaming = useUiStore((s) => s.streaming);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const { data: paths = [], isLoading, isError, error } = useQuery({
    queryKey: ["paths"],
    queryFn: fetchPaths,
    refetchInterval: streaming ? 5000 : 30_000,
  });

  async function onSelect(p: PathIndexEntry) {
    if (streaming) return;
    const doc = await fetchPath(p.id);
    loadPath(doc.meta, doc.steps, doc.snapshots ?? []);
  }

  async function onDelete(e: React.MouseEvent, p: PathIndexEntry) {
    e.stopPropagation();
    e.preventDefault();
    if (deletingId) return;

    const isRunning = p.status === "running";
    const isActiveStream = streaming && activePathId === p.id;
    const confirmMsg = isRunning
      ? `会话「${p.title.slice(0, 40)}」仍在分析中，强制删除将中断任务。确认？`
      : `删除会话「${p.title.slice(0, 40)}」？此操作不可恢复。`;
    if (!window.confirm(confirmMsg)) {
      return;
    }

    setDeleteError(null);
    setDeletingId(p.id);
    try {
      if (isActiveStream) {
        try {
          await cancelAnalysis(p.id);
        } catch {
          /* ignore */
        }
      }
      await deletePath(p.id, isRunning);
      if (activePathId === p.id) {
        clearThread();
      }
      await queryClient.invalidateQueries({ queryKey: ["paths"] });
      await queryClient.removeQueries({ queryKey: ["path-reports", p.id] });
      await queryClient.removeQueries({ queryKey: ["path-context", p.id] });
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  }

  function onNewChat() {
    clearThread();
    useUiStore.getState().setPage("chat");
  }

  return (
    <div className="sessBlock">
      <div className="sessHead">
        <span>会话</span>
      </div>
      <button
        type="button"
        className="sessNewChat"
        onClick={onNewChat}
        disabled={streaming}
        title="开始新的分析对话"
      >
        <span className="sessNewChatIcon" aria-hidden>
          +
        </span>
        <span className="sessNewChatLabel">新对话</span>
      </button>
      {deleteError ? <div className="sessErr">{deleteError}</div> : null}
      {isError ? (
        <div className="sessErr" title={error instanceof Error ? error.message : ""}>
          会话列表加载失败
        </div>
      ) : null}
      <div className="sessList">
        {isLoading ? <div className="sessEmpty">加载中…</div> : null}
        {!isLoading && paths.length === 0 ? (
          <div className="sessEmpty">暂无会话，发一条消息开始</div>
        ) : null}
        {paths.map((p) => (
          <div
            key={p.id}
            className={`sessRow ${activePathId === p.id ? "active" : ""}`}
          >
            <button
              type="button"
              className="sessItem"
              onClick={() => void onSelect(p)}
              disabled={streaming || deletingId === p.id}
            >
              <span className={`dot ${statusDot(p.status)}`} />
              <b>
                {pathKindBadge(p.kind) ? (
                  <span className="sessKind">{pathKindBadge(p.kind)}</span>
                ) : null}
                {p.title}
              </b>
              <small>
                {formatWhen(p.updated)} · {statusLabel(p)}
              </small>
            </button>
            <button
              type="button"
              className="sessDel"
              title={p.status === "running" ? "强制删除（将中断分析）" : "删除会话"}
              aria-label="删除会话"
              disabled={deletingId === p.id}
              onClick={(e) => void onDelete(e, p)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
