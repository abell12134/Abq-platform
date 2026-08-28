import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { fetchLlmHealth, fetchLlmProviders, routeCompose } from "../api/client";
import { fetchMemoryPreview } from "../api/memory";
import { detectKind } from "../lib/detectKind";
import { agentLabel } from "../lib/agentLabels";
import { useAnalyzeStream } from "./useAnalyzeStream";
import { useUiStore } from "../stores/ui";

export function useAppShellComposer() {
  const activePathId = useUiStore((s) => s.activePathId);
  const messages = useUiStore((s) => s.messages);
  const workflowSteps = useUiStore((s) => s.workflowSteps);
  const streaming = useUiStore((s) => s.streaming);
  const pipelinePhase = useUiStore((s) => s.pipelinePhase);
  const clearThread = useUiStore((s) => s.clearThread);
  const setAnalysisMeta = useUiStore((s) => s.setAnalysisMeta);
  const analysisMeta = useUiStore((s) => s.analysisMeta);
  const setPage = useUiStore((s) => s.setPage);
  const setMemoryHints = useUiStore((s) => s.setMemoryHints);
  const memoryHints = useUiStore((s) => s.memoryHints);
  const memorySummary = useUiStore((s) => s.memorySummary);

  const [input, setInput] = useState("");
  const [primaryOverride, setPrimaryOverride] = useState<string | null>(null);
  const [routeDraft, setRouteDraft] = useState("");
  const [memoryLoading, setMemoryLoading] = useState(false);
  const { start, cancel } = useAnalyzeStream();

  const focus = analysisMeta.focus ?? "";

  const { data: llmHealth, isError: llmHealthError } = useQuery({
    queryKey: ["llm-health"],
    queryFn: fetchLlmHealth,
    refetchInterval: 30_000,
  });

  const { data: providers = [] } = useQuery({
    queryKey: ["llm-providers"],
    queryFn: fetchLlmProviders,
  });

  const primaryProviders = providers.filter((p) => p.tier === "primary");
  const primary = llmHealth?.primary;
  const local = llmHealth?.local;

  const activePrimary =
    primaryProviders.find(
      (p) =>
        primaryOverride === `${p.id}:${p.model}` ||
        (!primaryOverride && p.id === primary?.provider),
    ) ?? primaryProviders[0];

  useEffect(() => {
    const needle = `${input} ${focus}`.trim();
    if (needle.length < 4 || streaming) {
      setRouteDraft("");
      return;
    }
    const timer = window.setTimeout(() => {
      void routeCompose({
        message: input,
        focus: focus.trim() || null,
        kind: analysisMeta.kind,
        realm: analysisMeta.realm,
      })
        .then((route) => {
          const kind =
            route.kind === "market" || route.kind === "portfolio"
              ? route.kind
              : analysisMeta.kind;
          setAnalysisMeta({
            ...useUiStore.getState().analysisMeta,
            kind,
            agent_ids: route.agent_ids,
            prompt_id: route.prompt_id,
            enable_debate: route.enable_debate,
            route_rationale: route.rationale,
          });
          setRouteDraft(route.rationale);
          if (route.memory_intent && needle.length >= 4) {
            setMemoryLoading(true);
            void fetchMemoryPreview({
              message: input,
              focus: focus.trim() || null,
              kind: analysisMeta.kind,
              symbol: analysisMeta.target,
            })
              .then((preview) => setMemoryHints(preview.hints, preview.summary))
              .catch(() => setMemoryHints([], null))
              .finally(() => setMemoryLoading(false));
          } else if (!route.memory_intent) {
            setMemoryHints([], null);
          }
        })
        .catch(() => setRouteDraft(""));
    }, 450);
    return () => window.clearTimeout(timer);
  }, [
    input,
    focus,
    streaming,
    analysisMeta.kind,
    analysisMeta.realm,
    analysisMeta.target,
    setAnalysisMeta,
    setMemoryHints,
  ]);

  const routeHint = useMemo(() => {
    if (!routeDraft && !analysisMeta.agent_ids?.length) return null;
    const agents = (analysisMeta.agent_ids ?? []).map(agentLabel).join(" · ");
    const debate = analysisMeta.enable_debate === true ? " · 含多空辩论" : "";
    return `${routeDraft || "标准组合"}${agents ? ` → ${agents}` : ""}${debate}`;
  }, [analysisMeta.agent_ids, analysisMeta.enable_debate, routeDraft]);

  async function handleSend() {
    const text = input.trim();
    if (!text || useUiStore.getState().streaming) return;
    const focusText = focus.trim() || null;
    const kind = detectKind(text, focusText ?? "");
    setInput("");
    setPage("chat");
    setMemoryHints([], null);
    setAnalysisMeta({
      ...analysisMeta,
      kind,
      realm: "a-share",
      focus: focusText,
    });
    await start({
      message: text,
      session_id: activePathId,
      kind,
      realm: "a-share",
      focus: focusText,
      agent_ids: analysisMeta.agent_ids ?? undefined,
      prompt_id: analysisMeta.prompt_id ?? undefined,
      enable_debate: analysisMeta.enable_debate ?? undefined,
      primary_model: primaryOverride,
    });
  }

  return {
    composerProps: {
      input,
      focus,
      routeHint,
      memoryHints,
      memorySummary,
      memoryLoading,
      streaming,
      pipelinePhase,
      messagesCount: messages.length,
      stepsCount: workflowSteps.length,
      activePathId,
      primaryOverride,
      primaryProviders,
      activePrimary,
      local,
      onInputChange: setInput,
      onFocusChange: (v: string) =>
        setAnalysisMeta({ ...useUiStore.getState().analysisMeta, focus: v.trim() || null }),
      onPrimaryChange: setPrimaryOverride,
      onSend: () => void handleSend(),
      onCancel: () => void cancel(),
      onNewChat: () => clearThread(),
    },
    llmHealth,
    llmHealthError,
    primary,
    local,
  };
}
