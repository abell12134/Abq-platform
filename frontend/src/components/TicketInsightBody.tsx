import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchOhlcv, fetchPath } from "../api/client";
import { KLineChart } from "./KLineChart";
import { MarkdownBody } from "./MarkdownBody";
import { agentLabel } from "../lib/agentLabels";
import { ohlcvWindowLabel, parseOhlcvLimit } from "../lib/ohlcvWindow";
import {
  buildTicketSummary,
  formatAsOf,
  formatPct,
  formatPrice,
  formatVolume,
  quoteFeedLabel,
} from "../lib/ticketSummary";
import type { AnalysisStep } from "../types/analysis";
import { useUiStore } from "../stores/ui";

const VIEW_ORDER = ["tech", "fundamental", "sentiment"] as const;

function viewPending(
  agent: (typeof VIEW_ORDER)[number],
  steps: AnalysisStep[],
  streamActiveIds: Record<string, boolean>,
  streaming: boolean,
): boolean {
  if (!streaming) return false;
  const hasBody = steps.some(
    (s) =>
      s.role === "assistant" &&
      s.agent === agent &&
      (s.result || s.thought).trim() &&
      (s.result || s.thought) !== "（模型未返回文本）",
  );
  if (hasBody) return false;
  const dataReady = steps.some((s) => s.agent === "calc_indicator");
  if (!dataReady) return false;
  const agentStreaming = steps.some(
    (s) => s.agent === agent && s.role === "assistant" && streamActiveIds[s.id],
  );
  return agentStreaming || true;
}

export function useTicketSummary() {
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
  return useMemo(() => buildTicketSummary(steps, reports), [steps, reports]);
}

export function TicketInsightBody({ compact = false }: { compact?: boolean }) {
  const steps = useUiStore((s) => s.workflowSteps);
  const streaming = useUiStore((s) => s.streaming);
  const streamActiveIds = useUiStore((s) => s.streamActiveIds);
  const analysisMeta = useUiStore((s) => s.analysisMeta);
  const summary = useTicketSummary();

  const userMessage = useMemo(
    () => steps.find((s) => s.role === "user")?.result?.trim() ?? "",
    [steps],
  );
  const ohlcvLimit = useMemo(
    () => parseOhlcvLimit(userMessage, analysisMeta.focus),
    [userMessage, analysisMeta.focus],
  );
  const hasQuoteData = steps.some((s) => s.agent === "fetch_quote");

  const { data: ohlcvData, isLoading: ohlcvLoading } = useQuery({
    queryKey: ["ohlcv", summary.symbol, ohlcvLimit, userMessage, analysisMeta.focus],
    queryFn: () =>
      fetchOhlcv(summary.symbol!, {
        limit: ohlcvLimit,
        message: userMessage,
        focus: analysisMeta.focus,
      }),
    enabled: Boolean(summary.symbol && hasQuoteData),
    staleTime: 60_000,
  });

  if (!summary.symbol) {
    return (
      <div className="ticketPanelEmpty">
        <p className="sub">发起单票分析后，这里会汇总行情、指标与三视角结论。</p>
      </div>
    );
  }

  const quote = summary.quote;
  const ind = summary.indicators;
  const pct = quote?.pct_change ?? (ind?.pct_1d as number | undefined);
  const pctClass =
    pct == null ? "" : pct > 0 ? "ticketUp" : pct < 0 ? "ticketDown" : "ticketFlat";
  const asOf = formatAsOf(quote?.as_of ?? ind?.as_of);
  const feed = quoteFeedLabel(quote?.status, quote?.as_of ?? ind?.as_of);

  return (
    <div className={`ticketInsightBody ${compact ? "compact" : ""}`}>
      <header className="ticketHero">
        <div>
          <div className="ticketSymbol">{summary.symbol}</div>
          <div className="ticketName">{quote?.name ?? "—"}</div>
          <div className="ticketAsOf">
            <span className={`ticketFeed ${pctClass}`}>{feed}</span>
            {asOf ? ` · as-of ${asOf}` : ""}
          </div>
        </div>
        <div className="ticketPriceBlock">
          <div className={`ticketPrice ${pctClass}`}>{formatPrice(quote?.price ?? ind?.close)}</div>
          <div className={`ticketChg ${pctClass}`}>
            {quote?.change != null ? `${quote.change > 0 ? "+" : ""}${quote.change.toFixed(2)} ` : ""}
            {formatPct(pct)}
          </div>
        </div>
      </header>

      <section className="ticketOhlc">
        <div>
          <span className="hudLabel">Open</span>
          <b>{formatPrice(quote?.open)}</b>
        </div>
        <div>
          <span className="hudLabel">High</span>
          <b>{formatPrice(quote?.high)}</b>
        </div>
        <div>
          <span className="hudLabel">Low</span>
          <b>{formatPrice(quote?.low)}</b>
        </div>
        <div>
          <span className="hudLabel">Prev</span>
          <b>{formatPrice(quote?.prev_close)}</b>
        </div>
        <div>
          <span className="hudLabel">Vol</span>
          <b>{formatVolume(quote?.volume)}</b>
        </div>
      </section>

      <section className="ticketGrid">
        <div className="ticketStat">
          <span className="ticketStatLabel">MA5</span>
          <span>{formatPrice(ind?.ma5)}</span>
        </div>
        <div className="ticketStat">
          <span className="ticketStatLabel">MA20</span>
          <span>{formatPrice(ind?.ma20)}</span>
        </div>
        <div className={`ticketStat ${ind?.pct_5d != null && ind.pct_5d > 0 ? "heat-up" : ind?.pct_5d != null && ind.pct_5d < 0 ? "heat-down" : ""}`}>
          <span className="ticketStatLabel">5日</span>
          <span className={ind?.pct_5d != null && ind.pct_5d > 0 ? "ticketUp" : ind?.pct_5d != null && ind.pct_5d < 0 ? "ticketDown" : ""}>
            {formatPct(ind?.pct_5d)}
          </span>
        </div>
        <div className={`ticketStat ${ind?.pct_20d != null && ind.pct_20d > 0 ? "heat-up" : ind?.pct_20d != null && ind.pct_20d < 0 ? "heat-down" : ""}`}>
          <span className="ticketStatLabel">20日</span>
          <span className={ind?.pct_20d != null && ind.pct_20d > 0 ? "ticketUp" : ind?.pct_20d != null && ind.pct_20d < 0 ? "ticketDown" : ""}>
            {formatPct(ind?.pct_20d)}
          </span>
        </div>
        <div className="ticketStat">
          <span className="ticketStatLabel">量比</span>
          <span>{ind?.vol_ratio_5d != null ? Number(ind.vol_ratio_5d).toFixed(2) : "—"}</span>
        </div>
      </section>

      <section className="ticketSection">
        <h2>行情走势</h2>
        {ohlcvLoading ? (
          <p className="sub">K 线加载中…</p>
        ) : ohlcvData?.bars?.length ? (
          <KLineChart
            bars={ohlcvData.bars}
            windowLabel={ohlcvData.window_label || ohlcvWindowLabel(ohlcvLimit)}
          />
        ) : hasQuoteData ? (
          <p className="sub">暂无 K 线数据</p>
        ) : (
          <p className="sub">取数完成后显示 K 线</p>
        )}
      </section>

      {summary.factors.length > 0 ? (
        <section className="ticketSection">
          <h2>因子截面</h2>
          <p className="ticketFactorHint sub">库内 passed_auto / live 因子 · 最近交易日</p>
          <div className="ticketFactors">
            {summary.factors.map((f) => (
              <div className="ticketFactorRow" key={f.id}>
                <div className="ticketFactorTop">
                  <span className="ticketFactorName">{f.name}</span>
                  <span className="ticketFactorPct">{f.percentile}</span>
                </div>
                <div className="ticketFactorMeta">
                  <code>{f.id}</code>
                  <span>值 {f.raw}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : streaming && steps.some((s) => s.agent === "calc_indicator") ? (
        <section className="ticketSection">
          <h2>因子截面</h2>
          <p className="sub">挂载中…</p>
        </section>
      ) : null}

      <section className="ticketSection">
        <h2>三视角</h2>
        <div className="ticketViews">
          {VIEW_ORDER.map((id) => {
            const body = summary.views[id];
            const pending = !body && viewPending(id, steps, streamActiveIds, streaming);
            if (!body) {
              return (
                <div className="ticketViewCard ticketViewEmpty" key={id}>
                  <div className="ticketViewHd">{agentLabel(id)}</div>
                  <p className="sub">{pending ? "分析中…" : "暂无结论"}</p>
                </div>
              );
            }
            return (
              <div className={`ticketViewCard tone-${id}`} key={id}>
                <div className="ticketViewHd">{agentLabel(id)}</div>
                <MarkdownBody text={body} />
              </div>
            );
          })}
        </div>
      </section>

      {summary.judge ? (
        <section className="ticketSection">
          <h2>综合研判</h2>
          <div className="ticketJudge">
            <MarkdownBody text={summary.judge} />
          </div>
        </section>
      ) : streaming ? (
        <section className="ticketSection">
          <h2>综合研判</h2>
          <p className="sub">分析中…</p>
        </section>
      ) : null}
    </div>
  );
}
