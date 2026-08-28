import { create } from "zustand";
import type { FactorMineRun } from "../types/library";
import type { AnalysisStep, ChatMessage, ContextSnapshot, PageId, PathIndexEntry } from "../types/analysis";

interface UiState {
  page: PageId;
  sessionTitle: string;
  pathId: string | null;
  activePathId: string | null;
  messages: ChatMessage[];
  workflowSteps: AnalysisStep[];
  contextSnapshots: ContextSnapshot[];
  streaming: boolean;
  streamError: string | null;
  pipelinePhase: string | null;
  ticketPanelOpen: boolean;
  portfolioPanelOpen: boolean;
  streamActiveIds: Record<string, boolean>;
  activeMineRun: FactorMineRun | null;
  activePortfolioId: string;
  memoryHints: string[];
  memorySummary: string | null;
  analysisMeta: import("../types/analysis").AnalysisMeta;
  setPage: (page: PageId) => void;
  setSessionTitle: (title: string) => void;
  setPathId: (id: string | null) => void;
  setActivePathId: (id: string | null) => void;
  appendStep: (step: AnalysisStep) => void;
  appendStreamToken: (stepId: string, agent: string, delta: string) => void;
  clearStreamActive: (stepId: string) => void;
  appendSnapshot: (snapshot: ContextSnapshot) => void;
  setContextSnapshots: (snapshots: ContextSnapshot[]) => void;
  loadPath: (meta: PathIndexEntry, steps: AnalysisStep[], snapshots?: ContextSnapshot[]) => void;
  clearThread: () => void;
  setStreaming: (v: boolean) => void;
  setStreamError: (msg: string | null) => void;
  setPipelinePhase: (label: string | null) => void;
  setTicketPanelOpen: (open: boolean) => void;
  setPortfolioPanelOpen: (open: boolean) => void;
  setAnalysisMeta: (meta: import("../types/analysis").AnalysisMeta) => void;
  setActiveMineRun: (run: FactorMineRun | null) => void;
  setActivePortfolioId: (id: string) => void;
  setMemoryHints: (hints: string[], summary?: string | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  page: "chat",
  sessionTitle: "新对话",
  pathId: null,
  activePathId: null,
  messages: [],
  workflowSteps: [],
  contextSnapshots: [],
  streaming: false,
  streamError: null,
  pipelinePhase: null,
  ticketPanelOpen: true,
  portfolioPanelOpen: true,
  streamActiveIds: {},
  activeMineRun: null,
  activePortfolioId: "default",
  memoryHints: [],
  memorySummary: null,
  analysisMeta: { kind: "single", realm: "a-share", focus: null, target: null, agent_ids: null },
  setPage: (page) => set({ page }),
  setSessionTitle: (sessionTitle) => set({ sessionTitle }),
  setPathId: (pathId) => set({ pathId }),
  setActivePathId: (activePathId) => set({ activePathId }),
  appendStep: (step) =>
    set((s) => {
      const idx = s.workflowSteps.findIndex((x) => x.id === step.id);
      const streamActiveIds = { ...s.streamActiveIds };
      delete streamActiveIds[step.id];

      if (idx >= 0) {
        const workflowSteps = [...s.workflowSteps];
        workflowSteps[idx] = step;
        const messages = s.messages.map((m) =>
          m.kind === "step" && m.step?.id === step.id ? { ...m, step } : m,
        );
        return { workflowSteps, messages, streamActiveIds };
      }
      return {
        messages: [...s.messages, { id: step.id, kind: "step", step }],
        workflowSteps: [...s.workflowSteps, step],
        streamActiveIds,
      };
    }),
  appendStreamToken: (stepId, agent, delta) =>
    set((s) => {
      const streamActiveIds = { ...s.streamActiveIds, [stepId]: true };
      const idx = s.workflowSteps.findIndex((x) => x.id === stepId);
      if (idx >= 0) {
        const prev = s.workflowSteps[idx]!;
        const text = (prev.result || "") + delta;
        const step: AnalysisStep = {
          ...prev,
          result: text,
          thought: text,
        };
        const workflowSteps = [...s.workflowSteps];
        workflowSteps[idx] = step;
        const messages = s.messages.map((m) =>
          m.kind === "step" && m.step?.id === stepId ? { ...m, step } : m,
        );
        return { workflowSteps, messages, streamActiveIds };
      }
      const ts = new Date().toISOString();
      const step: AnalysisStep = {
        id: stepId,
        agent,
        role: "assistant",
        thought: delta,
        result: delta,
        tool_calls: [],
        ts,
      };
      return {
        messages: [...s.messages, { id: stepId, kind: "step", step }],
        workflowSteps: [...s.workflowSteps, step],
        streamActiveIds,
      };
    }),
  clearStreamActive: (stepId) =>
    set((s) => {
      const streamActiveIds = { ...s.streamActiveIds };
      delete streamActiveIds[stepId];
      return { streamActiveIds };
    }),
  appendSnapshot: (snapshot) =>
    set((s) => ({
      contextSnapshots: [...s.contextSnapshots, snapshot],
    })),
  setContextSnapshots: (contextSnapshots) => set({ contextSnapshots }),
  loadPath: (meta, steps, snapshots = []) =>
    set({
      activePathId: meta.id,
      pathId: meta.id,
      sessionTitle: meta.title,
      messages: steps.map((step) => ({ id: step.id, kind: "step" as const, step })),
      workflowSteps: steps,
      contextSnapshots: snapshots,
      analysisMeta: {
        kind: meta.kind as import("../types/analysis").AnalysisMeta["kind"],
        realm: meta.realm as import("../types/analysis").AnalysisMeta["realm"],
        focus: meta.focus ?? null,
        target: meta.target ?? null,
        agent_ids: null,
      },
      page: "chat",
    }),
  clearThread: () =>
    set({
      messages: [],
      workflowSteps: [],
      contextSnapshots: [],
      pathId: null,
      activePathId: null,
      sessionTitle: "新对话",
      streamError: null,
      streamActiveIds: {},
      pipelinePhase: null,
      activeMineRun: null,
      memoryHints: [],
      memorySummary: null,
      analysisMeta: { kind: "single", realm: "a-share", focus: null, target: null, agent_ids: null },
    }),
  setStreaming: (streaming) => set({ streaming }),
  setStreamError: (streamError) => set({ streamError }),
  setPipelinePhase: (pipelinePhase) => set({ pipelinePhase }),
  setTicketPanelOpen: (ticketPanelOpen) => set({ ticketPanelOpen }),
  setPortfolioPanelOpen: (portfolioPanelOpen) => set({ portfolioPanelOpen }),
  setAnalysisMeta: (analysisMeta) => set({ analysisMeta }),
  setActiveMineRun: (activeMineRun) => set({ activeMineRun }),
  setActivePortfolioId: (activePortfolioId) => set({ activePortfolioId }),
  setMemoryHints: (memoryHints, memorySummary = null) => set({ memoryHints, memorySummary }),
}));
