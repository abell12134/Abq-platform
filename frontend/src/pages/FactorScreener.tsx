import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { applyFactorScreen, runFactorScreen } from "../api/library";
import { fetchPortfolios } from "../api/portfolio";
import { QueryErrorBanner } from "../components/QueryErrorBanner";
import type { FactorRecord, FactorScreenResult, FactorUniverse } from "../types/library";
import "./FactorScreener.css";

const METHODS = [
  { id: "ic_ir", label: "ICIR 加权" },
  { id: "ic", label: "|IC| 加权" },
  { id: "equal", label: "等权" },
] as const;

const SCREEN_STATUSES = new Set(["live", "paper_tracking", "passed_auto"]);

interface FactorScreenerProps {
  factors: FactorRecord[];
}

export function FactorScreener({ factors }: FactorScreenerProps) {
  const [universe, setUniverse] = useState<FactorUniverse>("csi300");
  const [method, setMethod] = useState<"equal" | "ic" | "ic_ir">("ic_ir");
  const [topN, setTopN] = useState(20);
  const [selected, setSelected] = useState<string[]>([]);
  const [useSynthetic, setUseSynthetic] = useState(false);
  const [portfolioId, setPortfolioId] = useState("default");
  const [applyMode, setApplyMode] = useState<"merge" | "replace">("merge");
  const [result, setResult] = useState<FactorScreenResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const portfoliosQuery = useQuery({
    queryKey: ["portfolios"],
    queryFn: fetchPortfolios,
  });

  const screenable = useMemo(
    () =>
      factors.filter(
        (f) => f.universe !== "market" && f.universe === universe && SCREEN_STATUSES.has(f.status),
      ),
    [factors, universe],
  );

  const screenMut = useMutation({
    mutationFn: () =>
      runFactorScreen({
        universe,
        factor_ids: selected,
        method,
        top_n: topN,
        use_synthetic: useSynthetic,
      }),
    onSuccess: (data) => {
      setResult(data);
      setError(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  const applyMut = useMutation({
    mutationFn: () => {
      if (!result?.picks?.length) throw new Error("请先运行选股");
      return applyFactorScreen({
        portfolio_id: portfolioId,
        symbols: result.picks.map((p) => p.symbol),
        mode: applyMode,
      });
    },
    onSuccess: () => setError(null),
    onError: (e: Error) => setError(e.message),
  });

  function toggleFactor(id: string) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  return (
    <section className="scrLib">
      <p className="sub">
        对沪深300/中证500成分股计算截面因子 z 分，按 IC/ICIR 方向加权合成得分，输出 Top N
        列表；可一键导入选组。
      </p>

      {error ? <div className="libErr">{error}</div> : null}
      <QueryErrorBanner
        isError={portfoliosQuery.isError}
        error={portfoliosQuery.error}
        label="自选组合列表加载失败"
      />
      {applyMut.isSuccess ? (
        <div className="scrOk">已导入选组「{portfolioId}」（{applyMut.data?.member_count} 只）</div>
      ) : null}

      <div className="scrGrid">
        <div className="scrPanel">
          <h3>筛选配置</h3>
          <div className="scrRow">
            <label>
              股票池
              <select value={universe} onChange={(e) => setUniverse(e.target.value as FactorUniverse)}>
                <option value="csi300">沪深300</option>
                <option value="csi500">中证500</option>
              </select>
            </label>
            <label>
              合成方式
              <select value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
                {METHODS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Top N
              <input
                type="number"
                min={1}
                max={100}
                value={topN}
                onChange={(e) => setTopN(Number(e.target.value) || 20)}
              />
            </label>
            <label className="scrCheck">
              <input
                type="checkbox"
                checked={useSynthetic}
                onChange={(e) => setUseSynthetic(e.target.checked)}
              />
              合成数据试跑
            </label>
          </div>

          <div className="scrFactors">
            <div className="scrFactorsHead">
              <span>参与因子（留空=自动选最多 6 个）</span>
              <button type="button" onClick={() => setSelected(screenable.map((f) => f.id))}>
                全选
              </button>
              <button type="button" onClick={() => setSelected([])}>
                清空
              </button>
            </div>
            {screenable.length === 0 ? (
              <p className="sub">当前股票池下没有 live / passed_auto 截面因子，请先在因子 Tab 挖掘或评测。</p>
            ) : (
              <ul className="scrFactorList">
                {screenable.map((f) => (
                  <li key={f.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={selected.includes(f.id)}
                        onChange={() => toggleFactor(f.id)}
                      />
                      <span className="scrFactorName">{f.name}</span>
                      <span className="scrFactorMeta">{f.id}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <button
            type="button"
            className="libPrimaryBtn"
            disabled={screenMut.isPending}
            onClick={() => void screenMut.mutate()}
          >
            {screenMut.isPending ? "选股中…" : "运行选股"}
          </button>
        </div>

        <div className="scrPanel">
          <h3>选股结果</h3>
          {!result ? (
            <p className="sub">运行后将显示按综合得分排序的列表。</p>
          ) : (
            <>
              <p className="scrMeta">
                截止 {result.as_of} · {result.universe} · {result.factors.length} 因子 · 样本{" "}
                {String(result.meta.panel?.n_stocks ?? "—")} 只
              </p>
              <table className="scrTable">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>代码</th>
                    <th>得分</th>
                  </tr>
                </thead>
                <tbody>
                  {result.picks.map((p) => (
                    <tr key={p.symbol}>
                      <td>{p.rank}</td>
                      <td>{p.symbol}</td>
                      <td>{p.score.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="scrApply">
                <h4>导入选组</h4>
                <div className="scrRow">
                  <label>
                    目标组合
                    <select value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)}>
                      {(portfoliosQuery.data ?? []).map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} ({p.id})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    模式
                    <select
                      value={applyMode}
                      onChange={(e) => setApplyMode(e.target.value as "merge" | "replace")}
                    >
                      <option value="merge">合并（去重追加）</option>
                      <option value="replace">替换全部成员</option>
                    </select>
                  </label>
                </div>
                <button
                  type="button"
                  className="libPrimaryBtn"
                  disabled={applyMut.isPending || !result.picks.length}
                  onClick={() => void applyMut.mutate()}
                >
                  {applyMut.isPending ? "导入中…" : `导入 ${result.picks.length} 只`}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
