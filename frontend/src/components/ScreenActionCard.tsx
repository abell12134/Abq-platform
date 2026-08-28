import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { applyFactorScreen } from "../api/library";
import { fetchPortfolios } from "../api/portfolio";
import type { FactorScreenResult } from "../types/library";
import "./ScreenActionCard.css";

interface ScreenActionCardProps {
  result: FactorScreenResult;
  onDiagnose?: (portfolioId: string) => void;
}

export function parseScreenResult(raw: string): FactorScreenResult | null {
  try {
    const body = JSON.parse(raw) as FactorScreenResult;
    if (!Array.isArray(body.picks) || body.picks.length === 0) return null;
    return body;
  } catch {
    return null;
  }
}

export function parseApplyResult(raw: string): { portfolio_id?: string; name?: string; member_count?: number } | null {
  try {
    const body = JSON.parse(raw) as { portfolio_id?: string; name?: string; member_count?: number; status?: string };
    if (body.status !== "ok" && !body.portfolio_id) return null;
    return body;
  } catch {
    return null;
  }
}

export function ScreenActionCard({ result, onDiagnose }: ScreenActionCardProps) {
  const [portfolioId, setPortfolioId] = useState("default");
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const portfoliosQuery = useQuery({
    queryKey: ["portfolios"],
    queryFn: fetchPortfolios,
  });

  const applyMut = useMutation({
    mutationFn: () =>
      applyFactorScreen({
        portfolio_id: portfolioId,
        symbols: result.picks.map((p) => p.symbol),
        mode,
      }),
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="screenCard">
      <div className="screenCardHead">
        <strong>因子选股 · Top {result.picks.length}</strong>
        <span className="screenMeta">
          {result.universe} · {result.as_of} · {result.method}
        </span>
      </div>
      <table className="screenTable">
        <thead>
          <tr>
            <th>#</th>
            <th>代码</th>
            <th>得分</th>
          </tr>
        </thead>
        <tbody>
          {result.picks.slice(0, 20).map((p) => (
            <tr key={p.symbol}>
              <td>{p.rank}</td>
              <td>{p.symbol}</td>
              <td>{p.score.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {error ? <div className="screenErr">{error}</div> : null}
      {applyMut.isSuccess ? (
        <div className="screenOk">
          已导入「{applyMut.data.name}」({applyMut.data.member_count} 只)
        </div>
      ) : null}
      <div className="screenActions">
        <select value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)} aria-label="目标组合">
          {(portfoliosQuery.data ?? [{ id: "default", name: "默认自选" }]).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select value={mode} onChange={(e) => setMode(e.target.value as "merge" | "replace")} aria-label="导入模式">
          <option value="merge">合并</option>
          <option value="replace">替换</option>
        </select>
        <button type="button" disabled={applyMut.isPending} onClick={() => void applyMut.mutate()}>
          {applyMut.isPending ? "导入中…" : "导入选组"}
        </button>
        {onDiagnose ? (
          <button
            type="button"
            className="screenPrimary"
            onClick={() => onDiagnose(applyMut.data?.portfolio_id ?? portfolioId)}
          >
            发起组合诊断
          </button>
        ) : null}
      </div>
    </div>
  );
}
