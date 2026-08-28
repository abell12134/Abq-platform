import { useQueryClient } from "@tanstack/react-query";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useCallback, useRef } from "react";
import {
  analyzeStreamUrl,
  cancelAnalysis,
  fetchPath,
  serializeAnalyzeRequest,
} from "../api/client";
import { fetchFactorRun } from "../api/library";
import { useUiStore } from "../stores/ui";
import type { AnalyzeRequest, ContextSnapshot, SseEvent } from "../types/analysis";
import type { FactorMineRun } from "../types/library";

const MINE_START_AGENTS = new Set(["start_factor_mine_llm", "start_factor_mine_gp"]);

function parseMineStart(stepResult: string): FactorMineRun | null {
  try {
    const body = JSON.parse(stepResult) as {
      run_id?: string;
      status?: string;
      kind?: string;
      message?: string;
    };
    if (!body.run_id) return null;
    return {
      run_id: body.run_id,
      status: body.status ?? "running",
      kind: body.kind,
      message: body.message,
    };
  } catch {
    return null;
  }
}

export function useAnalyzeStream() {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const appendStep = useUiStore((s) => s.appendStep);
  const appendStreamToken = useUiStore((s) => s.appendStreamToken);
  const appendSnapshot = useUiStore((s) => s.appendSnapshot);
  const activePathId = useUiStore((s) => s.activePathId);
  const setPathId = useUiStore((s) => s.setPathId);
  const setAnalysisMeta = useUiStore((s) => s.setAnalysisMeta);
  const analysisMeta = useUiStore((s) => s.analysisMeta);
  const setSessionTitle = useUiStore((s) => s.setSessionTitle);
  const setStreaming = useUiStore((s) => s.setStreaming);
  const setActivePathId = useUiStore((s) => s.setActivePathId);
  const setStreamError = useUiStore((s) => s.setStreamError);
  const setPipelinePhase = useUiStore((s) => s.setPipelinePhase);

  const setTicketPanelOpen = useUiStore((s) => s.setTicketPanelOpen);
  const setActiveMineRun = useUiStore((s) => s.setActiveMineRun);
  const setMemoryHints = useUiStore((s) => s.setMemoryHints);
  const loadPath = useUiStore((s) => s.loadPath);

  const cancel = useCallback(async () => {
    abortRef.current?.abort();
    abortRef.current = null;
    const pathId = useUiStore.getState().activePathId;
    if (pathId) {
      try {
        await cancelAnalysis(pathId);
      } catch {
        /* stream may already have ended */
      }
    }
    setStreaming(false);
    setPipelinePhase(null);
    setStreamError(null);
    void queryClient.invalidateQueries({ queryKey: ["paths"] });
  }, [queryClient, setPipelinePhase, setStreamError, setStreaming]);

  const start = useCallback(
    async (req: AnalyzeRequest) => {
      if (useUiStore.getState().streaming) return;

      abortRef.current?.abort();
      setStreaming(true);
      setStreamError(null);
      setPipelinePhase(null);
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      const sessionId = req.session_id ?? activePathId;

      if (sessionId) {
        try {
          const doc = await fetchPath(sessionId);
          loadPath(doc.meta, doc.steps, doc.snapshots ?? []);
        } catch {
          /* stream may still proceed for a just-created session */
        }
      } else {
        useUiStore.setState({
          workflowSteps: [],
          messages: [],
          contextSnapshots: [],
          streamActiveIds: {},
          pathId: null,
          activePathId: null,
        });
      }

      try {
        await fetchEventSource(analyzeStreamUrl(), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: serializeAnalyzeRequest({ ...req, session_id: sessionId }),
          signal: ctrl.signal,
          openWhenHidden: true,
          onmessage(ev) {
            if (!ev.data) return;
            const payload = JSON.parse(ev.data) as SseEvent;
            if (payload.type === "phase" && payload.label) {
              setPipelinePhase(payload.label);
            }
            if (payload.type === "memory" && payload.snapshot) {
              const snap = payload.snapshot as { hints?: string[] };
              setMemoryHints(snap.hints ?? [], payload.message ?? null);
            }
            if (payload.type === "compaction" && payload.snapshot) {
              appendSnapshot(payload.snapshot as ContextSnapshot);
            }
            if (payload.type === "token" && payload.step_id && payload.delta) {
              appendStreamToken(
                payload.step_id,
                payload.agent ?? "assistant",
                payload.delta,
              );
              if (payload.path_id) {
                setPathId(payload.path_id);
                setActivePathId(payload.path_id);
              }
            }
            if (payload.type === "step" && payload.step) {
              appendStep(payload.step);
              if (payload.path_id) {
                setPathId(payload.path_id);
                setActivePathId(payload.path_id);
              }
              if (payload.step.role === "user" && payload.step.result) {
                setSessionTitle(payload.step.result.slice(0, 40));
              }
              if (payload.step.agent === "fetch_quote" && payload.step.role === "tool") {
                setTicketPanelOpen(true);
                try {
                  const q = JSON.parse(payload.step.result) as { symbol?: string };
                  if (q.symbol) {
                    setAnalysisMeta({ ...analysisMeta, target: q.symbol });
                  }
                } catch {
                  /* ignore */
                }
              }
              if (
                payload.step.role === "tool" &&
                MINE_START_AGENTS.has(payload.step.agent)
              ) {
                const mineRun = parseMineStart(payload.step.result);
                if (mineRun) {
                  setActiveMineRun(mineRun);
                  void fetchFactorRun(mineRun.run_id)
                    .then(setActiveMineRun)
                    .catch(() => {});
                }
              }
            }
            if (payload.type === "done") {
              setStreaming(false);
              setPipelinePhase(null);
              abortRef.current = null;
              void queryClient.invalidateQueries({ queryKey: ["paths"] });
              ctrl.abort();
            }
            if (payload.type === "error") {
              setStreaming(false);
              setPipelinePhase(null);
              abortRef.current = null;
              if (payload.message !== "分析已取消") {
                setStreamError(payload.message ?? "分析失败");
              }
              void queryClient.invalidateQueries({ queryKey: ["paths"] });
              ctrl.abort();
            }
          },
          onerror(err) {
            if (ctrl.signal.aborted) throw err;
            setStreaming(false);
            setPipelinePhase(null);
            abortRef.current = null;
            setStreamError(err instanceof Error ? err.message : "连接中断");
            throw err;
          },
        });
      } finally {
        if (abortRef.current === ctrl) {
          abortRef.current = null;
        }
        setStreaming(false);
        setPipelinePhase(null);
      }
    },
    [
      activePathId,
      analysisMeta,
      appendSnapshot,
      appendStreamToken,
      appendStep,
      queryClient,
      loadPath,
      setActivePathId,
      setPathId,
      setSessionTitle,
      setStreaming,
      setStreamError,
      setPipelinePhase,
      setTicketPanelOpen,
      setAnalysisMeta,
      setActiveMineRun,
      setMemoryHints,
    ],
  );

  return { start, cancel };
}
