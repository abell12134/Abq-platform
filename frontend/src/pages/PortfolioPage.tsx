import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  createPortfolio,
  deletePortfolio,
  fetchPortfolioSnapshot,
  fetchPortfolioTracks,
  fetchPortfolios,
  recordPortfolioTrack,
  updatePortfolio,
} from "../api/portfolio";
import { useAnalyzeStream } from "../hooks/useAnalyzeStream";
import { formatPct, formatPrice, pctTone } from "../lib/portfolioView";
import { QueryErrorBanner } from "../components/QueryErrorBanner";
import { useUiStore } from "../stores/ui";
import type { PortfolioMember } from "../types/portfolio";
import "./PortfolioPage.css";

function parseMemberLines(text: string): PortfolioMember[] {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const out: PortfolioMember[] = [];
  for (const line of lines) {
    const m = line.match(/\b((?:sh|sz|bj)?\d{6})\b/i);
    if (!m) continue;
    const symbol = m[1]!.toLowerCase();
    const note = line.replace(m[0], "").replace(/[,，\s]+/g, " ").trim();
    out.push({ symbol, note: note || undefined });
  }
  return out;
}

function membersToText(members: PortfolioMember[]): string {
  return members
    .map((m) => (m.note ? `${m.symbol} ${m.note}` : m.symbol))
    .join("\n");
}

interface PortfolioPageProps {
  portfolioId: string;
  onPortfolioIdChange: (id: string) => void;
}

function slugifyId(name: string): string {
  const base = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 24);
  return base ? `pf-${base}` : `pf-${Date.now().toString(36)}`;
}

export function PortfolioPage({ portfolioId, onPortfolioIdChange }: PortfolioPageProps) {
  const queryClient = useQueryClient();
  const { start } = useAnalyzeStream();
  const streaming = useUiStore((s) => s.streaming);
  const setPage = useUiStore((s) => s.setPage);
  const setAnalysisMeta = useUiStore((s) => s.setAnalysisMeta);
  const analysisMeta = useUiStore((s) => s.analysisMeta);

  const [editOpen, setEditOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createId, setCreateId] = useState("");
  const [editText, setEditText] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const {
    data: portfolios = [],
    isError: portfoliosError,
    error: portfoliosErr,
  } = useQuery({
    queryKey: ["portfolios"],
    queryFn: fetchPortfolios,
  });

  const {
    data: snapshot,
    isLoading: snapLoading,
    isError: snapError,
    error: snapErr,
    refetch: refetchSnap,
  } = useQuery({
    queryKey: ["portfolio-snapshot", portfolioId],
    queryFn: () => fetchPortfolioSnapshot(portfolioId),
    refetchInterval: 60_000,
  });

  const {
    data: tracks = [],
    isError: tracksError,
    error: tracksErr,
  } = useQuery({
    queryKey: ["portfolio-tracks", portfolioId],
    queryFn: () => fetchPortfolioTracks(portfolioId),
  });

  const trackMut = useMutation({
    mutationFn: () => recordPortfolioTrack(portfolioId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portfolio-tracks", portfolioId] });
    },
  });

  const saveMut = useMutation({
    mutationFn: (members: PortfolioMember[]) =>
      updatePortfolio(portfolioId, { members }),
    onSuccess: () => {
      setEditOpen(false);
      setEditError(null);
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio-snapshot", portfolioId] });
      void refetchSnap();
    },
    onError: (err: Error) => setEditError(err.message),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createPortfolio({
        id: createId.trim() || slugifyId(createName),
        name: createName.trim(),
      }),
    onSuccess: (rec) => {
      setCreateOpen(false);
      setCreateName("");
      setCreateId("");
      onPortfolioIdChange(rec.id);
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
    },
    onError: (err: Error) => setEditError(err.message),
  });

  const deleteMut = useMutation({
    mutationFn: () => deletePortfolio(portfolioId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      onPortfolioIdChange("default");
    },
    onError: (err: Error) => setEditError(err.message),
  });

  const activePortfolio = useMemo(
    () => portfolios.find((p) => p.id === portfolioId) ?? portfolios[0],
    [portfolios, portfolioId],
  );

  async function handleDiagnose() {
    if (streaming) return;
    const name = snapshot?.name ?? activePortfolio?.name ?? "自选组合";
    setPage("chat");
    setAnalysisMeta({
      ...analysisMeta,
      kind: "portfolio",
      realm: "a-share",
      target: portfolioId,
      focus: null,
    });
    await start({
      message: `请对「${name}」做组合诊断，给出强弱排序与配置风险研判`,
      kind: "portfolio",
      realm: "a-share",
      target: portfolioId,
      primary_model: null,
    });
  }

  function openEdit() {
    const members = activePortfolio?.members ?? snapshot?.members ?? [];
    setEditText(
      membersToText(
        members.map((m) => ({
          symbol: m.symbol,
          note: "note" in m ? (m.note ?? undefined) : undefined,
        })),
      ),
    );
    setEditError(null);
    setEditOpen(true);
  }

  return (
    <div className="portfolioPage">
      <div className="pfLayout">
        <aside className="pfNav">
          <div className="pfNavHd">
            <span>我的组合</span>
            <button
              type="button"
              className="pfNavAdd"
              title="新建组合"
              onClick={() => {
                setEditError(null);
                setCreateOpen(true);
              }}
            >
              +
            </button>
          </div>
          <ul className="pfNavList">
            {portfolios.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className={p.id === portfolioId ? "active" : ""}
                  onClick={() => onPortfolioIdChange(p.id)}
                >
                  <strong>{p.name}</strong>
                  <span>{p.members.length} 只</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <div className="pfMain">
      <header className="pfHead">
        <div>
          <h1>选组跟踪</h1>
          <p className="sub">等权组合涨跌 · 成员快照 · 时间线</p>
        </div>
      </header>

      <QueryErrorBanner isError={portfoliosError} error={portfoliosErr} label="组合列表加载失败" />
      <QueryErrorBanner isError={snapError} error={snapErr} label="组合快照加载失败" />
      <QueryErrorBanner isError={tracksError} error={tracksErr} label="涨跌时间线加载失败" />

      <section className="pfOverview">
        <div className="pfOverviewMain">
          <h2>{snapshot?.name ?? activePortfolio?.name ?? "加载中…"}</h2>
          <p className="pfMeta">
            {snapshot?.member_count ?? "—"} 只成员
            {snapshot?.as_of ? ` · 更新 ${snapshot.as_of.slice(0, 16).replace("T", " ")}` : ""}
          </p>
          <div className="pfMetrics">
            <div className={`pfMetric tone-${pctTone(snapshot?.equal_weight_pct_1d)}`}>
              <span>今日（等权）</span>
              <strong>{formatPct(snapshot?.equal_weight_pct_1d)}</strong>
            </div>
            <div className={`pfMetric tone-${pctTone(snapshot?.equal_weight_chg_5d)}`}>
              <span>5日</span>
              <strong>{formatPct(snapshot?.equal_weight_chg_5d)}</strong>
            </div>
            <div className={`pfMetric tone-${pctTone(snapshot?.equal_weight_chg_20d)}`}>
              <span>20日</span>
              <strong>{formatPct(snapshot?.equal_weight_chg_20d)}</strong>
            </div>
          </div>
        </div>
        <div className="pfActions">
          <button type="button" className="pfPrimary" disabled={streaming} onClick={() => void handleDiagnose()}>
            发起组合诊断
          </button>
          <button
            type="button"
            className="pfSecondary"
            disabled={trackMut.isPending || snapLoading}
            onClick={() => trackMut.mutate()}
          >
            {trackMut.isPending ? "记录中…" : "记录今日快照"}
          </button>
          <button type="button" className="pfGhost" onClick={openEdit}>
            编辑成员
          </button>
          {portfolioId !== "default" ? (
            <button
              type="button"
              className="pfDanger"
              disabled={deleteMut.isPending}
              onClick={() => {
                if (window.confirm(`确定删除组合「${activePortfolio?.name ?? portfolioId}」？`)) {
                  deleteMut.mutate();
                }
              }}
            >
              删除组合
            </button>
          ) : null}
        </div>
      </section>

      {snapshot?.best_today || snapshot?.worst_today ? (
        <div className="pfHighlights">
          {snapshot.best_today ? (
            <span className="tone-up">
              今日最强 {snapshot.best_today.name ?? snapshot.best_today.symbol}{" "}
              {formatPct(snapshot.best_today.pct_change)}
            </span>
          ) : null}
          {snapshot.worst_today ? (
            <span className="tone-down">
              今日最弱 {snapshot.worst_today.name ?? snapshot.worst_today.symbol}{" "}
              {formatPct(snapshot.worst_today.pct_change)}
            </span>
          ) : null}
        </div>
      ) : null}

      <section className="pfSection">
        <h3>成员涨跌</h3>
        {snapLoading ? (
          <p className="pfEmpty">拉取行情中…</p>
        ) : !snapshot?.members.length ? (
          <p className="pfEmpty">暂无成员行情</p>
        ) : (
          <>
          <div className="pfHeat">
            {snapshot.members.map((m) => (
              <div key={m.symbol} className={`pfHeatTile tone-${pctTone(m.pct_change)}`}>
                <span className="pfHeatSym">{m.symbol.replace(/^(sh|sz|bj)/i, "")}</span>
                <span className="pfHeatName">{m.name ?? m.symbol}</span>
                <strong>{formatPct(m.pct_change)}</strong>
              </div>
            ))}
          </div>
          <div className="pfTableWrap">
            <table className="pfTable">
              <thead>
                <tr>
                  <th>标的</th>
                  <th>现价</th>
                  <th>今日</th>
                  <th>5日</th>
                  <th>20日</th>
                  <th>备注</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.members.map((m) => (
                  <tr key={m.symbol}>
                    <td>
                      <code>{m.symbol}</code>
                      {m.name ? <span className="pfName">{m.name}</span> : null}
                    </td>
                    <td>{formatPrice(m.price)}</td>
                    <td className={`tone-${pctTone(m.pct_change)}`}>{formatPct(m.pct_change)}</td>
                    <td className={`tone-${pctTone(m.chg_5d)}`}>{formatPct(m.chg_5d)}</td>
                    <td className={`tone-${pctTone(m.chg_20d)}`}>{formatPct(m.chg_20d)}</td>
                    <td className="pfNote">{m.note ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </section>

      <section className="pfSection">
        <h3>涨跌时间线</h3>
        {tracks.length === 0 ? (
          <p className="pfEmpty">尚无快照。点「记录今日快照」或完成一次组合诊断后写入。</p>
        ) : (
          <ul className="pfTimeline">
            {tracks.map((t) => (
              <li key={t.id} className="pfTimelineItem">
                <div className="pfTimelineDate">{t.date}</div>
                <div className="pfTimelineBody">
                  <span className={`pfTimelinePct tone-${pctTone(t.equal_weight_pct_1d)}`}>
                    组合 {formatPct(t.equal_weight_pct_1d)}
                  </span>
                  {t.best_symbol ? (
                    <span className="tone-up">
                      最强 {t.best_name ?? t.best_symbol} {formatPct(t.best_pct)}
                    </span>
                  ) : null}
                  {t.worst_symbol ? (
                    <span className="tone-down">
                      最弱 {t.worst_name ?? t.worst_symbol} {formatPct(t.worst_pct)}
                    </span>
                  ) : null}
                  {t.note ? <span className="pfTimelineNote">{t.note}</span> : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

        </div>
      </div>

      {editError && !editOpen && !createOpen ? <p className="pfErr pfErrBar">{editError}</p> : null}

      {createOpen ? (
        <div className="pfModalBackdrop" role="presentation" onClick={() => setCreateOpen(false)}>
          <div
            className="pfModal"
            role="dialog"
            aria-label="新建组合"
            onClick={(e) => e.stopPropagation()}
          >
            <h3>新建组合</h3>
            <label className="pfField">
              名称
              <input
                value={createName}
                onChange={(e) => {
                  setCreateName(e.target.value);
                  if (!createId) setCreateId(slugifyId(e.target.value));
                }}
                placeholder="如：新能源自选"
              />
            </label>
            <label className="pfField">
              ID（英文）
              <input
                value={createId}
                onChange={(e) => setCreateId(e.target.value)}
                placeholder="pf-new-energy"
                spellCheck={false}
              />
            </label>
            {editError ? <p className="pfErr">{editError}</p> : null}
            <div className="pfModalActions">
              <button type="button" className="pfGhost" onClick={() => setCreateOpen(false)}>
                取消
              </button>
              <button
                type="button"
                className="pfPrimary"
                disabled={createMut.isPending || !createName.trim()}
                onClick={() => createMut.mutate()}
              >
                {createMut.isPending ? "创建中…" : "创建"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {editOpen ? (
        <div className="pfModalBackdrop" role="presentation" onClick={() => setEditOpen(false)}>
          <div
            className="pfModal"
            role="dialog"
            aria-label="编辑成员"
            onClick={(e) => e.stopPropagation()}
          >
            <h3>编辑成员</h3>
            <p className="sub">每行一个代码，可加备注：`sh600519 茅台`</p>
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={8}
              spellCheck={false}
            />
            {editError ? <p className="pfErr">{editError}</p> : null}
            <div className="pfModalActions">
              <button type="button" className="pfGhost" onClick={() => setEditOpen(false)}>
                取消
              </button>
              <button
                type="button"
                className="pfPrimary"
                disabled={saveMut.isPending}
                onClick={() => {
                  const members = parseMemberLines(editText);
                  if (!members.length) {
                    setEditError("请至少保留一只有效股票代码");
                    return;
                  }
                  saveMut.mutate(members);
                }}
              >
                {saveMut.isPending ? "保存中…" : "保存"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
