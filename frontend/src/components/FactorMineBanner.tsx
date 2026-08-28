import { useEffect } from "react";
import { fetchFactorRun } from "../api/library";
import { useUiStore } from "../stores/ui";
import type { FactorMineRun } from "../types/library";
import "../pages/LibraryPage.css";
import "./FactorMineBanner.css";

function minePct(run: FactorMineRun): number {
  const total = run.rounds || run.round || 0;
  if (!total) return run.status === "done" ? 100 : 0;
  return Math.min(100, Math.round(((run.round ?? 0) / Math.max(1, total)) * 100));
}

export function FactorMineBanner() {
  const run = useUiStore((s) => s.activeMineRun);
  const setActiveMineRun = useUiStore((s) => s.setActiveMineRun);

  useEffect(() => {
    if (!run?.run_id || run.status !== "running") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await fetchFactorRun(run.run_id);
        if (!cancelled) setActiveMineRun(next);
      } catch {
        /* ignore transient poll errors */
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [run?.run_id, run?.status, setActiveMineRun]);

  if (!run?.run_id) return null;

  const funnel = run.funnel;
  const pct = minePct(run);
  const done = run.status === "done" || run.status === "error";

  return (
    <div className={`factorMineBanner ${done ? "done" : "running"}`}>
      <div className="factorMineBannerHead">
        <strong>因子挖掘</strong>
        <span className="factorMineBannerMeta">
          {run.kind ?? "mine"} · {run.run_id.slice(0, 8)}
        </span>
        {done ? (
          <button type="button" className="factorMineDismiss" onClick={() => setActiveMineRun(null)}>
            关闭
          </button>
        ) : null}
      </div>
      <div className="mineProgress">
        <div className="mineBar">
          <i style={{ width: `${run.status === "done" ? 100 : pct}%` }} />
        </div>
        <p>{run.message || (run.status === "running" ? "挖掘进行中…" : run.status)}</p>
        {funnel ? (
          <div className="mineFunnel">
            <span>提议 {funnel.proposed ?? 0}</span>
            <span>解析失败 {funnel.parse_fail ?? 0}</span>
            <span>评测 {funnel.evaled ?? 0}</span>
            <span>过关 {funnel.passed ?? 0}</span>
            <span>淘汰 {funnel.rejected ?? 0}</span>
          </div>
        ) : null}
        {run.error ? <p className="factorMineError">{run.error}</p> : null}
      </div>
    </div>
  );
}
