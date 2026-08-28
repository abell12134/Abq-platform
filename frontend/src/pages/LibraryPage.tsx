import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  createAgent,
  createPrompt,
  deleteAgent,
  deletePrompt,
  fetchAgentRecords,
  fetchFactors,
  fetchPrompts,
  fetchTools,
  updateAgent,
  updatePrompt,
} from "../api/library";
import { agentLabel } from "../lib/agentLabels";
import type {
  AgentCreate,
  AgentRecord,
  AgentUpdate,
  LibraryTab,
  PromptCategory,
  PromptCreate,
  PromptRecord,
  PromptUpdate,
} from "../types/library";
import { PROMPT_CATEGORIES } from "../types/library";
import { FactorLibrary } from "./FactorLibrary";
import { FactorScreener } from "./FactorScreener";
import { KnowledgeLibrary } from "./KnowledgeLibrary";
import { QueryErrorBanner } from "../components/QueryErrorBanner";
import "./LibraryPage.css";
import "../pages/pages.css";

const TABS: { id: LibraryTab; label: string }[] = [
  { id: "agents", label: "Agent" },
  { id: "prompts", label: "提示词" },
  { id: "tools", label: "工具" },
  { id: "factors", label: "因子" },
  { id: "screener", label: "选股" },
  { id: "knowledge", label: "知识库" },
];

const LIB_TAB_KEY = "abq-lib-tab";

function initialTab(): LibraryTab {
  const stored = sessionStorage.getItem(LIB_TAB_KEY);
  return TABS.some((t) => t.id === stored) ? (stored as LibraryTab) : "factors";
}

export function LibraryPage() {
  const [tab, setTab] = useState<LibraryTab>(initialTab);
  const [editingPrompt, setEditingPrompt] = useState<PromptRecord | "new" | null>(null);
  const [editingAgent, setEditingAgent] = useState<AgentRecord | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const agentsQuery = useQuery({ queryKey: ["library-agents"], queryFn: fetchAgentRecords });
  const promptsQuery = useQuery({ queryKey: ["library-prompts"], queryFn: fetchPrompts });
  const toolsQuery = useQuery({ queryKey: ["library-tools"], queryFn: fetchTools });
  const factorsQuery = useQuery({ queryKey: ["library-factors"], queryFn: fetchFactors });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["library-agents"] });
    void queryClient.invalidateQueries({ queryKey: ["library-prompts"] });
    void queryClient.invalidateQueries({ queryKey: ["library-factors"] });
    void queryClient.invalidateQueries({ queryKey: ["agents"] });
  };

  const deletePromptMut = useMutation({
    mutationFn: deletePrompt,
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  const deleteAgentMut = useMutation({
    mutationFn: deleteAgent,
    onSuccess: invalidate,
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="pad libPage">
      <header className="libHead">
        <div>
          <h1>三库</h1>
          <p className="sub">管理 Agent、提示词、工具与因子。因子是算子树，评测走同一套准入。</p>
        </div>
      </header>

      <div className="libTabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={tab === t.id ? "active" : ""}
            onClick={() => {
              setTab(t.id);
              sessionStorage.setItem(LIB_TAB_KEY, t.id);
              setError(null);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error ? <div className="libErr">{error}</div> : null}

      {tab === "agents" ? (
        <section>
          <div className="libToolbar">
            <span>{agentsQuery.data?.length ?? 0} 个 agent</span>
            <button type="button" className="libPrimaryBtn" onClick={() => setEditingAgent("new")}>
              新建 Agent
            </button>
          </div>
          {agentsQuery.isLoading ? <p className="sub">加载中…</p> : null}
          <QueryErrorBanner isError={agentsQuery.isError} error={agentsQuery.error} label="Agent 列表加载失败" />
          <div className="agentGrid">
            {(agentsQuery.data ?? []).map((a) => (
              <article className="agentCard libCard" key={a.id}>
                <header>
                  <strong>{a.name}</strong>
                  <span className="tierBadge">{a.model_tier}</span>
                </header>
                <div className="kv">id {a.id}</div>
                <div className="kv">prompt {a.prompt_id}</div>
                <div className="kv">status {a.status}</div>
                <div className="kv">
                  tools {a.tools.length ? a.tools.map(agentLabel).join(" · ") : "（无）"}
                </div>
                {a.builtin ? <span className="libBuiltin">内置</span> : null}
                <div className="libCardActions">
                  <button type="button" onClick={() => setEditingAgent(a)}>
                    编辑
                  </button>
                  {!a.builtin ? (
                    <button
                      type="button"
                      className="danger"
                      onClick={() => {
                        if (window.confirm(`删除 agent「${a.name}」？`)) {
                          setError(null);
                          deleteAgentMut.mutate(a.id);
                        }
                      }}
                    >
                      删除
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {tab === "prompts" ? (
        <section>
          <div className="libToolbar">
            <span>{promptsQuery.data?.length ?? 0} 条提示词</span>
            <button type="button" className="libPrimaryBtn" onClick={() => setEditingPrompt("new")}>
              新建提示词
            </button>
          </div>
          {promptsQuery.isLoading ? <p className="sub">加载中…</p> : null}
          <QueryErrorBanner isError={promptsQuery.isError} error={promptsQuery.error} label="提示词列表加载失败" />
          <div className="libList">
            {(promptsQuery.data ?? []).map((p) => (
              <article className="libListRow" key={p.id}>
                <div className="libListMain">
                  <strong>{p.id}</strong>
                  <span className="libTag">{p.category}</span>
                  {p.builtin ? <span className="libBuiltin">内置</span> : null}
                  <p className="sub libPreview">
                    {(p.persona || p.instructions).slice(0, 120)}
                    {(p.persona || p.instructions).length > 120 ? "…" : ""}
                  </p>
                </div>
                <div className="libCardActions">
                  <button type="button" onClick={() => setEditingPrompt(p)}>
                    编辑
                  </button>
                  {!p.builtin ? (
                    <button
                      type="button"
                      className="danger"
                      onClick={() => {
                        if (window.confirm(`删除提示词「${p.id}」？`)) {
                          setError(null);
                          deletePromptMut.mutate(p.id);
                        }
                      }}
                    >
                      删除
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {tab === "tools" ? (
        <section>
          <div className="libToolbar">
            <span>{toolsQuery.data?.length ?? 0} 个工具（只读）</span>
          </div>
          {toolsQuery.isLoading ? <p className="sub">加载中…</p> : null}
          <QueryErrorBanner isError={toolsQuery.isError} error={toolsQuery.error} label="工具列表加载失败" />
          <div className="agentGrid">
            {(toolsQuery.data ?? []).map((t) => (
              <article className="agentCard libCard" key={t.id}>
                <header>
                  <strong>{agentLabel(t.id)}</strong>
                  <span className="libTag">code</span>
                </header>
                <div className="kv mono">{t.id}</div>
                <p className="sub libToolDesc">{t.description}</p>
                {t.guidance ? <p className="sub libToolGuidance">{t.guidance}</p> : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {tab === "factors" ? <FactorLibrary /> : null}
      {tab === "screener" ? (
        <>
          <QueryErrorBanner isError={factorsQuery.isError} error={factorsQuery.error} label="因子列表加载失败" />
          <FactorScreener factors={factorsQuery.data ?? []} />
        </>
      ) : null}
      {tab === "knowledge" ? <KnowledgeLibrary /> : null}

      {editingPrompt !== null ? (
        <PromptEditorModal
          initial={editingPrompt}
          onClose={() => setEditingPrompt(null)}
          onSaved={() => {
            invalidate();
            setEditingPrompt(null);
            setError(null);
          }}
          onError={setError}
        />
      ) : null}

      {editingAgent !== null ? (
        <AgentEditorModal
          initial={editingAgent}
          prompts={promptsQuery.data ?? []}
          tools={toolsQuery.data ?? []}
          onClose={() => setEditingAgent(null)}
          onSaved={() => {
            invalidate();
            setEditingAgent(null);
            setError(null);
          }}
          onError={setError}
        />
      ) : null}
    </div>
  );
}

function PromptEditorModal({
  initial,
  onClose,
  onSaved,
  onError,
}: {
  initial: PromptRecord | "new";
  onClose: () => void;
  onSaved: () => void;
  onError: (msg: string) => void;
}) {
  const isNew = initial === "new";
  const [id, setId] = useState(isNew ? "" : initial.id);
  const [category, setCategory] = useState<PromptCategory>(
    isNew ? "analysis" : initial.category,
  );
  const [persona, setPersona] = useState(isNew ? "" : initial.persona);
  const [instructions, setInstructions] = useState(isNew ? "" : initial.instructions);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      if (isNew) {
        const body: PromptCreate = { id: id.trim(), category, persona, instructions };
        await createPrompt(body);
      } else {
        const body: PromptUpdate = { category, persona, instructions };
        await updatePrompt(initial.id, body);
      }
      onSaved();
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
          <h2>{isNew ? "新建提示词" : `编辑 · ${initial.id}`}</h2>
          <button type="button" className="libModalClose" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="libForm">
          {isNew ? (
            <label>
              ID
              <input
                value={id}
                onChange={(e) => setId(e.target.value)}
                placeholder="my-analysis-instructions"
              />
            </label>
          ) : null}
          <label>
            分类
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as PromptCategory)}
            >
              {PROMPT_CATEGORIES.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Persona（人设）
            <textarea value={persona} onChange={(e) => setPersona(e.target.value)} rows={5} />
          </label>
          <label>
            Instructions（分析协议）
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={12}
            />
          </label>
          <p className="sub">
            可用变量：{" "}
            <code>
              {"{{symbol}} {{company_name}} {{realm}} {{as_of}} {{focus}} {{model}} {{path_kind}}"}
            </code>
          </p>
        </div>
        <footer className="libModalFt">
          <button type="button" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="libPrimaryBtn"
            disabled={saving || (isNew && !id.trim())}
            onClick={() => void handleSave()}
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function AgentEditorModal({
  initial,
  prompts,
  tools,
  onClose,
  onSaved,
  onError,
}: {
  initial: AgentRecord | "new";
  prompts: PromptRecord[];
  tools: { id: string }[];
  onClose: () => void;
  onSaved: () => void;
  onError: (msg: string) => void;
}) {
  const isNew = initial === "new";
  const [id, setId] = useState(isNew ? "" : initial.id);
  const [name, setName] = useState(isNew ? "" : initial.name);
  const [modelTier, setModelTier] = useState(isNew ? "primary" : initial.model_tier);
  const [promptId, setPromptId] = useState(
    isNew ? (prompts[0]?.id ?? "") : initial.prompt_id,
  );
  const [status, setStatus] = useState(isNew ? "active" : initial.status);
  const [selectedTools, setSelectedTools] = useState<string[]>(isNew ? [] : [...initial.tools]);
  const [saving, setSaving] = useState(false);

  function toggleTool(toolId: string) {
    setSelectedTools((prev) =>
      prev.includes(toolId) ? prev.filter((t) => t !== toolId) : [...prev, toolId],
    );
  }

  async function handleSave() {
    setSaving(true);
    try {
      if (isNew) {
        const body: AgentCreate = {
          id: id.trim(),
          name: name.trim(),
          model_tier: modelTier,
          prompt_id: promptId,
          tools: selectedTools,
          status,
        };
        await createAgent(body);
      } else {
        const body: AgentUpdate = {
          name: name.trim(),
          model_tier: modelTier,
          prompt_id: promptId,
          tools: selectedTools,
          status,
        };
        await updateAgent(initial.id, body);
      }
      onSaved();
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
          <h2>{isNew ? "新建 Agent" : `编辑 · ${initial.name}`}</h2>
          <button type="button" className="libModalClose" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="libForm">
          {isNew ? (
            <label>
              ID
              <input value={id} onChange={(e) => setId(e.target.value)} placeholder="my-agent" />
            </label>
          ) : null}
          <label>
            名称
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            模型层级
            <select
              value={modelTier}
              onChange={(e) => setModelTier(e.target.value as "primary" | "local")}
            >
              <option value="primary">primary（主模型）</option>
              <option value="local">local（本地小模型）</option>
            </select>
          </label>
          <label>
            状态
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as "active" | "draft")}
            >
              <option value="active">active</option>
              <option value="draft">draft</option>
            </select>
          </label>
          <label>
            提示词
            <select value={promptId} onChange={(e) => setPromptId(e.target.value)}>
              {prompts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.id} ({p.category})
                </option>
              ))}
            </select>
          </label>
          <fieldset className="libToolPick">
            <legend>工具</legend>
            <div className="libToolChecks">
              {tools.map((t) => (
                <label key={t.id} className="libToolCheck">
                  <input
                    type="checkbox"
                    checked={selectedTools.includes(t.id)}
                    onChange={() => toggleTool(t.id)}
                  />
                  {agentLabel(t.id)}
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        <footer className="libModalFt">
          <button type="button" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="libPrimaryBtn"
            disabled={saving || (isNew && !id.trim()) || !name.trim() || !promptId}
            onClick={() => void handleSave()}
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </footer>
      </div>
    </div>
  );
}
