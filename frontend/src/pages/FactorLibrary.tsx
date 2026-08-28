import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  createFactor,
  deleteFactor,
  evalFactor,
  fetchFactorRun,
  fetchFactors,
  revalidatePaperFactors,
  startGpMine,
  startLlmMine,
  synthesizeFactors,
  updateFactor,
} from "../api/library";
import { FactorIcChart } from "../components/FactorIcChart";
import { QueryErrorBanner } from "../components/QueryErrorBanner";
import type {
  FactorCreate,
  FactorMineRun,
  FactorOrigin,
  FactorRecord,
  FactorStatus,
  FactorSynthMethod,
  FactorUniverse,
  FactorUpdate,
} from "../types/library";

const ORIGIN_LABEL: Record<FactorOrigin, string> = {
  catalog: "种子",
  manual: "手工",
  llm: "LLM",
  gp: "GP",
  synth: "合成",
};

const FACTOR_STATUS_LABEL: Record<FactorStatus, string> = {
  candidate: "候选",
  rejected: "淘汰",
  passed_auto: "过自动关",
  paper_tracking: "纸面跟踪",
  frozen: "冻结",
  retired: "退休",
  live: "live",
};

const UNIVERSE_LABEL: Record<FactorUniverse, string> = {
  csi300: "沪深300",
  csi500: "中证500",
  market: "大盘择时",
};

type IcStats = {
  ic_mean?: number | null;
  icir?: number | null;
  ic_pos_ratio?: number | null;
  valid_days?: number;
};

function icStats(f: FactorRecord): IcStats {
  const metrics = f.metrics as { ic_stats?: IcStats } | undefined;
  return metrics?.ic_stats ?? {};
}

function formatNum(v: number | null | undefined, digits = 4): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—";
}

function icTone(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "";
  return Math.abs(v) >= 0.02 ? "icOk" : "icWeak";
}

function gateFlags(f: FactorRecord) {
  const m = f.metrics as {
    gate1_passed?: boolean;
    gate2_passed?: boolean;
    gate3_passed?: boolean;
    gate4_passed?: boolean;
  };
  return [m.gate1_passed, m.gate2_passed, m.gate3_passed, m.gate4_passed];
}

export function FactorLibrary() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<FactorRecord | "new" | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [evaluatingId, setEvaluatingId] = useState<string | null>(null);
  const [evalAll, setEvalAll] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [originFilter, setOriginFilter] = useState<string>("all");
  const [mineOpen, setMineOpen] = useState(false);
  const [mineMode, setMineMode] = useState<"llm" | "gp">("llm");
  const [themeHint, setThemeHint] = useState("");
  const [rounds, setRounds] = useState(2);
  const [k, setK] = useState(3);
  const [population, setPopulation] = useState(80);
  const [generations, setGenerations] = useState(8);
  const [gpTrack, setGpTrack] = useState<"market" | "cs">("market");
  const [mineSynthetic, setMineSynthetic] = useState(true);
  const [runId, setRunId] = useState<string | null>(null);
  const [synthOpen, setSynthOpen] = useState(false);
  const [synthMethod, setSynthMethod] = useState<FactorSynthMethod>("equal");
  const [synthSelected, setSynthSelected] = useState<string[]>([]);
  const [synthBusy, setSynthBusy] = useState(false);
  const [synthSynthetic, setSynthSynthetic] = useState(true);
  const [paperBusy, setPaperBusy] = useState(false);

  const factorsQuery = useQuery({ queryKey: ["library-factors"], queryFn: fetchFactors });
  const runQuery = useQuery({
    queryKey: ["factor-run", runId],
    queryFn: () => fetchFactorRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" ? 1200 : false;
    },
  });

  const run = runQuery.data;
  const mining = run?.status === "running";

  const factors = factorsQuery.data ?? [];
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = factors.filter((f) => {
      if (statusFilter !== "all" && f.status !== statusFilter) return false;
      if (originFilter !== "all" && f.origin !== originFilter) return false;
      if (!needle) return true;
      const hay = `${f.id} ${f.name} ${f.formula} ${f.theme.join(" ")} ${f.hypothesis}`.toLowerCase();
      return hay.includes(needle);
    });
    rows.sort((a, b) => {
      const ia = icStats(a).ic_mean;
      const ib = icStats(b).ic_mean;
      const aN = typeof ia === "number" ? Math.abs(ia) : -1;
      const bN = typeof ib === "number" ? Math.abs(ib) : -1;
      return bN - aN;
    });
    return rows;
  }, [factors, originFilter, q, statusFilter]);

  const selected = factors.find((f) => f.id === selectedId) ?? filtered[0] ?? null;

  const synthEligible = useMemo(
    () =>
      factors.filter(
        (f) =>
          f.universe !== "market" &&
          (f.status === "passed_auto" || f.status === "paper_tracking" || f.status === "live"),
      ),
    [factors],
  );

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["library-factors"] });
  }

  const deleteMut = useMutation({
    mutationFn: deleteFactor,
    onSuccess: (_ok, id) => {
      invalidate();
      if (selectedId === id) setSelectedId(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  async function handlePaperRevalidate() {
    setPaperBusy(true);
    setError(null);
    try {
      const out = await revalidatePaperFactors();
      invalidate();
      setNotice(`纸面重评完成：${out.count} 个因子已更新`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "纸面重评失败");
    } finally {
      setPaperBusy(false);
    }
  }

  async function handleEval(factorId: string, synthetic: boolean) {
    setEvaluatingId(factorId);
    setError(null);
    setNotice(null);
    try {
      const out = await evalFactor({ factor_id: factorId, use_synthetic: synthetic });
      invalidate();
      setSelectedId(factorId);
      const ic = out.metrics.ic_stats?.ic_mean;
      const reason = out.metrics.reject_reason || FACTOR_STATUS_LABEL[(out.metrics.status as FactorStatus) ?? "candidate"];
      const src = synthetic ? "合成数据" : "真实行情";
      setNotice(`${src}评测完成 · IC ${formatNum(ic)} · ${reason}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "评测失败");
    } finally {
      setEvaluatingId(null);
    }
  }

  async function handleEvalAll() {
    setError(null);
    setNotice(null);
    try {
      for (let i = 0; i < filtered.length; i += 1) {
        setEvalAll(`${i + 1}/${filtered.length}`);
        setEvaluatingId(filtered[i].id);
        await evalFactor({ factor_id: filtered[i].id, use_synthetic: true });
      }
      invalidate();
      setNotice(`已用合成数据评测 ${filtered.length} 个因子`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "批量评测失败");
      invalidate();
    } finally {
      setEvaluatingId(null);
      setEvalAll(null);
    }
  }

  async function handleSynth() {
    if (synthSelected.length < 2) {
      setError("请至少选择 2 个因子参与合成");
      return;
    }
    setSynthBusy(true);
    setError(null);
    setNotice(null);
    try {
      const out = await synthesizeFactors({
        method: synthMethod,
        factor_ids: synthSelected,
        use_synthetic: synthSynthetic,
      });
      invalidate();
      setSelectedId(out.factor.id);
      const gate5 = out.gate5_note ? ` · ${out.gate5_note}` : "";
      setNotice(`合成完成 · ${out.factor.id} · ${FACTOR_STATUS_LABEL[out.factor.status]}${gate5}`);
      setSynthOpen(false);
      setSynthSelected([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "合成失败");
    } finally {
      setSynthBusy(false);
    }
  }

  async function handleMine() {
    setError(null);
    setNotice(null);
    try {
      const started =
        mineMode === "gp"
          ? await startGpMine({
              track: gpTrack,
              universe: gpTrack === "cs" ? "csi300" : "market",
              population,
              generations,
              use_synthetic: mineSynthetic,
            })
          : await startLlmMine({
              universe: "csi300",
              rounds,
              k,
              theme_hint: themeHint.trim(),
              use_synthetic: mineSynthetic,
            });
      setRunId(started.run_id);
      setMineOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法开始挖掘");
    }
  }

  useEffect(() => {
    if (!run || (run.status !== "done" && run.status !== "error")) return;
    const key = `acked-${run.run_id}-${run.status}`;
    if (sessionStorage.getItem(key) === "1") return;
    sessionStorage.setItem(key, "1");
    void queryClient.invalidateQueries({ queryKey: ["library-factors"] });
    if (run.status === "done") {
      const ids = run.accepted_ids?.length ? ` · ${run.accepted_ids.join("、")}` : "";
      setNotice((run.message || `挖掘完成，过关 ${run.funnel?.passed ?? 0} 个`) + ids);
    } else {
      setError(run.error || run.message || "挖掘失败");
    }
  }, [queryClient, run]);

  return (
    <section className="factorLib">
      {error ? <div className="libErr">{error}</div> : null}
      {notice ? (
        <div className="libNotice">
          {notice}
          <button type="button" className="libNoticeClose" onClick={() => setNotice(null)}>
            ×
          </button>
        </div>
      ) : null}

      <div className="libToolbar factorToolbar">
        <div className="factorFilters">
          <input
            className="factorSearch"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索名称 / 公式 / 主题"
          />
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">全部状态</option>
            {(Object.keys(FACTOR_STATUS_LABEL) as FactorStatus[]).map((s) => (
              <option key={s} value={s}>
                {FACTOR_STATUS_LABEL[s]}
              </option>
            ))}
          </select>
          <select value={originFilter} onChange={(e) => setOriginFilter(e.target.value)}>
            <option value="all">全部来源</option>
            {(Object.keys(ORIGIN_LABEL) as FactorOrigin[]).map((o) => (
              <option key={o} value={o}>
                {ORIGIN_LABEL[o]}
              </option>
            ))}
          </select>
          <span className="factorCount">
            {filtered.length}/{factors.length}
          </span>
        </div>
        <div className="factorToolbarBtns">
          <button type="button" disabled={paperBusy} onClick={() => void handlePaperRevalidate()}>
            {paperBusy ? "纸面重评中…" : "纸面重评"}
          </button>
          <button type="button" disabled={Boolean(evalAll) || filtered.length === 0} onClick={() => void handleEvalAll()}>
            {evalAll ? `评测 ${evalAll}` : "全部合成评测"}
          </button>
          <button
            type="button"
            className={mineOpen && mineMode === "llm" ? "active" : ""}
            onClick={() => {
              setMineMode("llm");
              setMineOpen(true);
              setSynthOpen(false);
            }}
          >
            LLM 挖掘
          </button>
          <button
            type="button"
            className={mineOpen && mineMode === "gp" ? "active" : ""}
            onClick={() => {
              setMineMode("gp");
              setMineOpen(true);
              setSynthOpen(false);
            }}
          >
            GP 发明
          </button>
          <button
            type="button"
            className={synthOpen ? "active" : ""}
            onClick={() => {
              setSynthOpen(!synthOpen);
              setMineOpen(false);
            }}
          >
            因子合成
          </button>
          <button type="button" className="libPrimaryBtn" onClick={() => setEditing("new")}>
            新建因子
          </button>
        </div>
      </div>

      {synthOpen ? (
        <SynthPanel
          method={synthMethod}
          selected={synthSelected}
          eligible={synthEligible}
          busy={synthBusy}
          useSynthetic={synthSynthetic}
          onMethod={setSynthMethod}
          onToggle={(id) =>
            setSynthSelected((prev) =>
              prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
            )
          }
          onSynthetic={setSynthSynthetic}
          onStart={() => void handleSynth()}
          onClose={() => setSynthOpen(false)}
        />
      ) : null}

      {mineOpen ? (
        <MinePanel
          mode={mineMode}
          gpTrack={gpTrack}
          themeHint={themeHint}
          rounds={rounds}
          k={k}
          population={population}
          generations={generations}
          mineSynthetic={mineSynthetic}
          mining={mining}
          run={run}
          onMode={(m) => setMineMode(m)}
          onGpTrack={setGpTrack}
          onThemeHint={setThemeHint}
          onRounds={setRounds}
          onK={setK}
          onPopulation={setPopulation}
          onGenerations={setGenerations}
          onSynthetic={setMineSynthetic}
          onStart={() => void handleMine()}
          onClose={() => setMineOpen(false)}
        />
      ) : null}

      {factorsQuery.isLoading ? <p className="sub">加载中…</p> : null}
      <QueryErrorBanner isError={factorsQuery.isError} error={factorsQuery.error} label="因子列表加载失败" />
      <QueryErrorBanner isError={runQuery.isError} error={runQuery.error} label="挖掘任务状态加载失败" />

      <div className={`factorWorkbench ${selected ? "hasDetail" : ""}`}>
        <div className="factorGrid">
          {filtered.map((f) => {
            const ic = icStats(f);
            const busy = evaluatingId === f.id;
            const shownStatus = ((f.metrics as { status?: FactorStatus }).status || f.status) as FactorStatus;
            return (
              <article
                key={f.id}
                className={`agentCard libCard factorCard ${selected?.id === f.id ? "selected" : ""}`}
                onClick={() => setSelectedId(f.id)}
              >
                <header>
                  <strong>{f.name}</strong>
                  <span className={`libStatus libStatus-${shownStatus}`}>{FACTOR_STATUS_LABEL[shownStatus] ?? shownStatus}</span>
                </header>
                <div className="kv">
                  {ORIGIN_LABEL[f.origin]} · {UNIVERSE_LABEL[f.universe]}
                  {f.theme.length ? ` · ${f.theme[0]}` : ""}
                </div>
                <p className="sub libFormula">{f.formula}</p>
                <div className={`factorIc ${icTone(ic.ic_mean)}`}>
                  <span>IC {formatNum(ic.ic_mean)}</span>
                  <span>IR {formatNum(ic.icir, 2)}</span>
                  <GateDots flags={gateFlags(f)} />
                </div>
                {f.reject_reason ? <p className="sub libPreview">{f.reject_reason}</p> : null}
                <div className="libCardActions" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    disabled={busy || Boolean(evalAll)}
                    title="内存合成面板，几秒出结果，只用来通流程"
                    onClick={() => void handleEval(f.id, true)}
                  >
                    {busy ? "评测中…" : "合成数据"}
                  </button>
                  <button
                    type="button"
                    disabled={busy || Boolean(evalAll)}
                    title="本地 qlib 真实行情，首次可能较慢"
                    onClick={() => void handleEval(f.id, false)}
                  >
                    真实行情
                  </button>
                </div>
              </article>
            );
          })}
        </div>

        {selected ? (
          <FactorDetail
            factor={selected}
            busy={evaluatingId === selected.id || Boolean(evalAll)}
            onEval={(synthetic) => void handleEval(selected.id, synthetic)}
            onEdit={() => setEditing(selected)}
            onDelete={
              !selected.builtin && selected.origin !== "catalog"
                ? () => {
                    if (window.confirm(`删除因子「${selected.name}」？`)) {
                      setError(null);
                      deleteMut.mutate(selected.id);
                    }
                  }
                : undefined
            }
          />
        ) : (
          <aside className="factorDetail factorDetailEmpty">
            <p className="sub">点一张卡片查看闸门、经济逻辑和评测。</p>
          </aside>
        )}
      </div>

      {editing !== null ? (
        <FactorEditorModal
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={(id) => {
            invalidate();
            setEditing(null);
            setError(null);
            if (id) setSelectedId(id);
            setNotice("已保存。建议先用「合成数据」跑一遍准入。");
          }}
          onError={setError}
        />
      ) : null}
    </section>
  );
}

function GateDots({ flags }: { flags: Array<boolean | undefined> }) {
  const labels = ["初筛", "去重", "样本外", "逻辑"];
  return (
    <span className="gateDots" title="闸门 1–4：初筛 / 去重 / 样本外 / 逻辑">
      {flags.map((ok, i) => (
        <i
          key={labels[i]}
          className={ok === true ? "pass" : ok === false ? "fail" : "unk"}
          title={`${i + 1} ${labels[i]} ${ok === true ? "过" : ok === false ? "未过" : "未评"}`}
        />
      ))}
    </span>
  );
}

function FactorDetail({
  factor,
  busy,
  onEval,
  onEdit,
  onDelete,
}: {
  factor: FactorRecord;
  busy: boolean;
  onEval: (synthetic: boolean) => void;
  onEdit: () => void;
  onDelete?: () => void;
}) {
  const ic = icStats(factor);
  const m = factor.metrics as {
    gate1_passed?: boolean;
    gate2_passed?: boolean;
    gate3_passed?: boolean;
    gate4_passed?: boolean;
    gate5_note?: string;
    ic_series?: Array<{ date: string; ic: number }>;
    gate1_detail?: { ic_mean?: number; icir?: number; threshold_ic_mean?: number; threshold_icir?: number };
    gate2_detail?: { max_corr?: number | null; corr_with?: string | null };
    gate3_detail?: { ic_is_mean?: number | null; ic_oos_mean?: number | null };
    gate4_note?: string;
    mode?: string;
  };
  const evaluated = typeof ic.ic_mean === "number";
  const shownStatus = ((factor.metrics as { status?: FactorStatus }).status || factor.status) as FactorStatus;
  const gates = [
    {
      n: 1,
      name: "初筛",
      ok: m.gate1_passed,
          hint: `|IC|≥${m.gate1_detail?.threshold_ic_mean ?? 0.02} 且 |ICIR|≥${m.gate1_detail?.threshold_icir ?? 0.25}`,
    },
    {
      n: 2,
      name: "去重",
      ok: m.gate2_passed,
      hint: m.gate2_detail?.corr_with
        ? `与 ${m.gate2_detail.corr_with} 相关 ${formatNum(m.gate2_detail.max_corr)}`
        : "与库内因子 |相关| < 0.7",
    },
    {
      n: 3,
      name: "样本外",
      ok: m.gate3_passed,
      hint:
        evaluated && m.gate3_detail
          ? `IS ${formatNum(m.gate3_detail.ic_is_mean)} · OOS ${formatNum(m.gate3_detail.ic_oos_mean)}`
          : "同号且 OOS 不过弱",
    },
    {
      n: 4,
      name: "逻辑",
      ok: m.gate4_passed,
      hint: m.gate4_note || "经济逻辑 ≥ 8 字",
    },
  ];

  return (
    <aside className="factorDetail">
      <header>
        <div>
          <h3>{factor.name}</h3>
          <div className="kv">
            {factor.id} · {ORIGIN_LABEL[factor.origin]} · {UNIVERSE_LABEL[factor.universe]}
          </div>
        </div>
        <span className={`libStatus libStatus-${shownStatus}`}>{FACTOR_STATUS_LABEL[shownStatus] ?? shownStatus}</span>
      </header>
      <p className="sub libFormula">
        {(factor.metrics as { synth?: { display_formula?: string } })?.synth?.display_formula || factor.formula}
      </p>
      {(factor.metrics as { synth?: { components?: string[]; gate5_note?: string } })?.synth ? (
        <div className="factorSynthMeta">
          <h4>合成成分</h4>
          <p className="sub">
            {(
              (factor.metrics as { synth?: { components?: string[] } }).synth?.components ?? []
            ).join(" · ")}
          </p>
          {(factor.metrics as { synth?: { gate5_note?: string } }).synth?.gate5_note ? (
            <p className="sub">Gate 5：{(factor.metrics as { synth?: { gate5_note?: string } }).synth?.gate5_note}</p>
          ) : null}
        </div>
      ) : null}
      <div className={`factorIc ${icTone(ic.ic_mean)}`}>
        <span>IC {formatNum(ic.ic_mean)}</span>
        <span>IR {formatNum(ic.icir, 2)}</span>
        <span>有效日 {ic.valid_days ?? "—"}</span>
        {typeof ic.ic_pos_ratio === "number" ? <span>正IC {(ic.ic_pos_ratio * 100).toFixed(0)}%</span> : null}
      </div>
      {m.ic_series?.length ? <FactorIcChart series={m.ic_series} /> : null}
      {m.gate5_note ? <p className="factorReason">Gate 5：{m.gate5_note}</p> : null}
      {factor.reject_reason ? <p className="factorReason">{factor.reject_reason}</p> : null}
      <div className="gateList">
        {gates.map((g) => (
          <div key={g.n} className={`gateRow ${g.ok === true ? "pass" : g.ok === false ? "fail" : ""}`}>
            <b>
              {g.n} {g.name}
            </b>
            <span>{g.ok === true ? "过" : g.ok === false ? "未过" : "未评"}</span>
            <small>{g.hint}</small>
          </div>
        ))}
      </div>
      <div className="factorHyp">
        <h4>经济逻辑</h4>
        <p>{factor.hypothesis.trim() || "尚未填写。过自动关后补逻辑才能进纸面跟踪。"}</p>
      </div>
      <div className="libCardActions">
        <button type="button" disabled={busy} onClick={() => onEval(true)}>
          {busy ? "评测中…" : "合成数据"}
        </button>
        <button type="button" disabled={busy} onClick={() => onEval(false)}>
          真实行情
        </button>
        <button type="button" onClick={onEdit}>
          编辑
        </button>
        {onDelete ? (
          <button type="button" className="danger" onClick={onDelete}>
            删除
          </button>
        ) : null}
      </div>
    </aside>
  );
}

function SynthPanel({
  method,
  selected,
  eligible,
  busy,
  useSynthetic,
  onMethod,
  onToggle,
  onSynthetic,
  onStart,
  onClose,
}: {
  method: FactorSynthMethod;
  selected: string[];
  eligible: FactorRecord[];
  busy: boolean;
  useSynthetic: boolean;
  onMethod: (m: FactorSynthMethod) => void;
  onToggle: (id: string) => void;
  onSynthetic: (v: boolean) => void;
  onStart: () => void;
  onClose: () => void;
}) {
  return (
    <div className="minePanel">
      <div className="mineMode">
        <strong>因子合成</strong>
        <button type="button" className="mineClose" onClick={onClose}>
          收起
        </button>
      </div>
      <p className="sub">
        从 passed_auto / 纸面 / live 截面因子合成新因子（equal / IC / ICIR 加权），过关后可进纸面跟踪。
      </p>
      <div className="mineRow">
        <label>
          方法
          <select value={method} onChange={(e) => onMethod(e.target.value as FactorSynthMethod)}>
            <option value="equal">等权 equal</option>
            <option value="ic">IC 加权</option>
            <option value="ic_ir">ICIR 加权</option>
          </select>
        </label>
        <label className="mineCheck">
          <input type="checkbox" checked={useSynthetic} onChange={(e) => onSynthetic(e.target.checked)} />
          合成数据（快）
        </label>
      </div>
      <div className="factorSynthPick">
        {eligible.length === 0 ? (
          <p className="sub">暂无可用因子。请先评测并让因子达到 passed_auto 或以上。</p>
        ) : (
          eligible.map((f) => (
            <label key={f.id} className="factorSynthItem">
              <input
                type="checkbox"
                checked={selected.includes(f.id)}
                onChange={() => onToggle(f.id)}
              />
              <span>
                {f.name} <code>{f.id}</code>
              </span>
              <span className="factorSynthIc">IC {formatNum(icStats(f).ic_mean)}</span>
            </label>
          ))
        )}
      </div>
      <div className="mineRow">
        <button type="button" className="libPrimaryBtn" disabled={busy || selected.length < 2} onClick={onStart}>
          {busy ? "合成中…" : `合成 ${selected.length} 个因子`}
        </button>
      </div>
    </div>
  );
}

function MinePanel({
  mode,
  gpTrack,
  themeHint,
  rounds,
  k,
  population,
  generations,
  mineSynthetic,
  mining,
  run,
  onMode,
  onGpTrack,
  onThemeHint,
  onRounds,
  onK,
  onPopulation,
  onGenerations,
  onSynthetic,
  onStart,
  onClose,
}: {
  mode: "llm" | "gp";
  gpTrack: "market" | "cs";
  themeHint: string;
  rounds: number;
  k: number;
  population: number;
  generations: number;
  mineSynthetic: boolean;
  mining: boolean;
  run: FactorMineRun | undefined;
  onMode: (m: "llm" | "gp") => void;
  onGpTrack: (t: "market" | "cs") => void;
  onThemeHint: (v: string) => void;
  onRounds: (v: number) => void;
  onK: (v: number) => void;
  onPopulation: (v: number) => void;
  onGenerations: (v: number) => void;
  onSynthetic: (v: boolean) => void;
  onStart: () => void;
  onClose: () => void;
}) {
  const funnel = run?.funnel;
  const total = run?.rounds || (mode === "gp" ? generations : rounds);
  const pct =
    run && total
      ? Math.min(100, Math.round(((run.round ?? 0) / Math.max(1, total)) * 100))
      : 0;
  return (
    <div className="minePanel">
      <div className="mineMode">
        <button type="button" className={mode === "llm" ? "active" : ""} onClick={() => onMode("llm")}>
          LLM 截面
        </button>
        <button type="button" className={mode === "gp" ? "active" : ""} onClick={() => onMode("gp")}>
          GP 发明
        </button>
        <button type="button" className="mineClose" onClick={onClose}>
          收起
        </button>
      </div>
      <p className="sub">
        {mode === "llm"
          ? "模型按白名单算子提议公式，解析成树后再走同一套准入。解析失败会丢掉，不会 eval。"
          : gpTrack === "cs"
            ? "截面 GP：在日×股票面板上用 Rank IC 适应度进化算子树（含大盘 broadcast 原语）。公式转 IR 后走同一套准入；无经济逻辑，最多停在「过自动关」。"
            : "大盘择时 GP：用指数原语做符号回归（gplearn）。公式会转成算子树再过准入；无经济逻辑，最多停在「过自动关」，不会自动 live。"}
      </p>
      <div className="mineRow">
        {mode === "gp" ? (
          <div className="mineMode mineGpTrack">
            <button
              type="button"
              className={gpTrack === "market" ? "active" : ""}
              onClick={() => onGpTrack("market")}
            >
              轨 A · 大盘择时
            </button>
            <button
              type="button"
              className={gpTrack === "cs" ? "active" : ""}
              onClick={() => onGpTrack("cs")}
            >
              轨 B · 截面选股
            </button>
          </div>
        ) : null}
        {mode === "llm" ? (
          <>
            <label>
              主题侧重
              <input
                value={themeHint}
                onChange={(e) => onThemeHint(e.target.value)}
                placeholder="例如：量价背离、相对大盘强弱"
              />
            </label>
            <label>
              轮次
              <input
                type="number"
                min={1}
                max={5}
                value={rounds}
                onChange={(e) => onRounds(Number(e.target.value) || 1)}
              />
            </label>
            <label>
              每轮条数
              <input type="number" min={1} max={6} value={k} onChange={(e) => onK(Number(e.target.value) || 1)} />
            </label>
          </>
        ) : (
          <>
            <label>
              种群
              <input
                type="number"
                min={20}
                max={200}
                value={population}
                onChange={(e) => onPopulation(Number(e.target.value) || 80)}
              />
            </label>
            <label>
              代数
              <input
                type="number"
                min={3}
                max={30}
                value={generations}
                onChange={(e) => onGenerations(Number(e.target.value) || 8)}
              />
            </label>
          </>
        )}
        <label className="mineCheck">
          <input type="checkbox" checked={mineSynthetic} onChange={(e) => onSynthetic(e.target.checked)} />
          用合成数据（快，适合试流程）
        </label>
        <button type="button" className="libPrimaryBtn" disabled={mining} onClick={onStart}>
          {mining ? "挖掘中…" : mode === "gp" ? "开始发明公式" : "开始挖掘"}
        </button>
      </div>
      {run ? (
        <div className="mineProgress">
          <div className="mineBar">
            <i style={{ width: `${run.status === "done" ? 100 : pct}%` }} />
          </div>
          <p>{run.message}</p>
          {funnel ? (
            <div className="mineFunnel">
              <span>提议 {funnel.proposed ?? 0}</span>
              <span>解析失败 {funnel.parse_fail ?? 0}</span>
              <span>评测 {funnel.evaled ?? 0}</span>
              <span>过关 {funnel.passed ?? 0}</span>
              <span>淘汰 {funnel.rejected ?? 0}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function FactorEditorModal({
  initial,
  onClose,
  onSaved,
  onError,
}: {
  initial: FactorRecord | "new";
  onClose: () => void;
  onSaved: (id?: string) => void;
  onError: (msg: string) => void;
}) {
  const isNew = initial === "new";
  const [id, setId] = useState(isNew ? "" : initial.id);
  const [name, setName] = useState(isNew ? "" : initial.name);
  const [formula, setFormula] = useState(isNew ? "" : initial.formula);
  const [hypothesis, setHypothesis] = useState(isNew ? "" : initial.hypothesis);
  const [universe, setUniverse] = useState<FactorUniverse>(isNew ? "csi300" : initial.universe);
  const [theme, setTheme] = useState(isNew ? "momentum" : (initial.theme[0] ?? "momentum"));
  const [status, setStatus] = useState<FactorStatus>(isNew ? "candidate" : initial.status);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      if (isNew) {
        const body: FactorCreate = {
          id: id.trim(),
          name: name.trim(),
          formula: formula.trim(),
          hypothesis,
          theme: theme ? [theme] : [],
          universe,
        };
        const rec = await createFactor(body);
        onSaved(rec.id);
      } else {
        const body: FactorUpdate = {
          name: name.trim(),
          hypothesis,
          status,
          theme: theme ? [theme] : [],
          formula: initial.builtin ? undefined : formula.trim(),
        };
        await updateFactor(initial.id, body);
        onSaved(initial.id);
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="libModalBackdrop" onClick={onClose}>
      <div className="libModal" onClick={(e) => e.stopPropagation()}>
        <header className="libModalHd">
          <h2>{isNew ? "新建因子" : `编辑 · ${initial.name}`}</h2>
          <button type="button" className="libModalClose" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="libForm">
          {isNew ? (
            <label>
              ID
              <input value={id} onChange={(e) => setId(e.target.value)} placeholder="rel_strength_20" />
            </label>
          ) : null}
          <label>
            名称
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            公式（白名单算子，如 sub(div(close, delay(close, 20)), 1)）
            <textarea
              value={formula}
              onChange={(e) => setFormula(e.target.value)}
              rows={3}
              disabled={!isNew && initial.builtin}
            />
          </label>
          <label>
            经济逻辑
            <textarea value={hypothesis} onChange={(e) => setHypothesis(e.target.value)} rows={4} />
          </label>
          {isNew ? (
            <label>
              股票池
              <select value={universe} onChange={(e) => setUniverse(e.target.value as FactorUniverse)}>
                <option value="csi300">沪深300 截面</option>
                <option value="csi500">中证500 截面</option>
                <option value="market">大盘择时</option>
              </select>
            </label>
          ) : (
            <label>
              状态
              <select value={status} onChange={(e) => setStatus(e.target.value as FactorStatus)}>
                {(Object.keys(FACTOR_STATUS_LABEL) as FactorStatus[]).map((s) => (
                  <option key={s} value={s}>
                    {FACTOR_STATUS_LABEL[s]}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            主题
            <input value={theme} onChange={(e) => setTheme(e.target.value)} />
          </label>
        </div>
        <footer className="libModalFt">
          <button type="button" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="libPrimaryBtn"
            disabled={saving || !name.trim() || !formula.trim() || (isNew && !id.trim())}
            onClick={() => void handleSave()}
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </footer>
      </div>
    </div>
  );
}
