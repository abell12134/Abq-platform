import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchPath } from "../api/client";
import { MarkdownBody } from "./MarkdownBody";
import { buildPortfolioSummary, formatPct } from "../lib/portfolioSummary";
import { pctTone } from "../lib/portfolioView";
import { useUiStore } from "../stores/ui";
import "./FactorIcChart.css";

export function usePortfolioSummary() {
  const steps = useUiStore((s) => s.workflowSteps);
  const pathId = useUiStore((s) => s.pathId);
  const streaming = useUiStore((s) => s.streaming);

  const { data: pathDoc } = useQuery({
    queryKey: ["path-reports", pathId],
    queryFn: () => fetchPath(pathId!),
    enabled: Boolean(pathId),
    refetchInterval: streaming ? 3000 : false,
  });

  const reports = pathDoc?.reports as import("../lib/ticketSummary").PathReports | undefined;
  return useMemo(() => buildPortfolioSummary(steps, reports), [steps, reports]);
}

export function PortfolioInsightBody({ compact = false }: { compact?: boolean }) {
  const summary = usePortfolioSummary();
  const hasData = summary.members.length > 0 || summary.portfolioReport || summary.judge;

  if (!hasData) {
    return (
      <div className="ticketPanelEmpty">
        <p className="sub">发起组合诊断后，这里会汇总成员涨跌与组合研判。</p>
      </div>
    );
  }

  return (
    <div className={`ticketInsightBody ${compact ? "compact" : ""}`}>
      <header className="ticketHero">
        <div>
          <div className="ticketSymbol">{summary.name ?? "自选组合"}</div>
          <div className="ticketName">{summary.memberCount} 只成员 · 等权</div>
        </div>
        <div className={`ticketPrice tone-${pctTone(summary.equalWeightPct1d)}`}>
          {formatPct(summary.equalWeightPct1d)}
        </div>
      </header>

      <div className="ticketGrid">
        <div className="ticketStat">
          <span>5日</span>
          <strong className={`tone-${pctTone(summary.equalWeightChg5d)}`}>
            {formatPct(summary.equalWeightChg5d)}
          </strong>
        </div>
        <div className="ticketStat">
          <span>20日</span>
          <strong className={`tone-${pctTone(summary.equalWeightChg20d)}`}>
            {formatPct(summary.equalWeightChg20d)}
          </strong>
        </div>
        <div className="ticketStat">
          <span>成员</span>
          <strong>{summary.memberCount}</strong>
        </div>
      </div>

      {summary.members.length > 0 ? (
        <section className="ticketSection">
          <h2>成员涨跌</h2>
          <ul className="pfInsightMembers">
            {summary.members.map((m) => (
              <li key={m.symbol}>
                <code>{m.symbol}</code>
                {m.name ? <span className="pfName">{m.name}</span> : null}
                <span className={`tone-${pctTone(m.pct_change)}`}>{formatPct(m.pct_change)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {summary.portfolioReport ? (
        <section className="ticketSection">
          <h2>组合诊断</h2>
          <div className="ticketViewCard">
            <MarkdownBody text={summary.portfolioReport} />
          </div>
        </section>
      ) : null}

      {summary.judge ? (
        <section className="ticketSection ticketJudge">
          <h2>综合研判</h2>
          <MarkdownBody text={summary.judge} />
        </section>
      ) : null}
    </div>
  );
}
