import type {
  AgentCreate,
  AgentDetail,
  AgentRecord,
  AgentUpdate,
  FactorCreate,
  FactorEvalResult,
  FactorMineGpRequest,
  FactorMineLlmRequest,
  FactorMineRun,
  FactorRecord,
  FactorScreenApplyRequest,
  FactorScreenRequest,
  FactorScreenResult,
  FactorSynthesizeRequest,
  FactorSynthesizeResult,
  FactorUpdate,
  PromptCreate,
  PromptRecord,
  PromptUpdate,
  ToolRecord,
} from "../types/library";
import { API_BASE, parseApiError } from "./http";

export async function fetchPrompts(): Promise<PromptRecord[]> {
  const res = await fetch(`${API_BASE}/prompts`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = await res.json();
  return data.prompts ?? [];
}

export async function fetchPrompt(id: string): Promise<PromptRecord> {
  const res = await fetch(`${API_BASE}/prompts/${id}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function createPrompt(body: PromptCreate): Promise<PromptRecord> {
  const res = await fetch(`${API_BASE}/prompts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function updatePrompt(id: string, body: PromptUpdate): Promise<PromptRecord> {
  const res = await fetch(`${API_BASE}/prompts/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function deletePrompt(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/prompts/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await parseApiError(res));
}

export async function fetchAgentRecords(): Promise<AgentRecord[]> {
  const res = await fetch(`${API_BASE}/agents`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = await res.json();
  return data.agents ?? [];
}

export async function fetchAgentDetail(id: string): Promise<AgentDetail> {
  const res = await fetch(`${API_BASE}/agents/${id}?expand=true`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function createAgent(body: AgentCreate): Promise<AgentRecord> {
  const res = await fetch(`${API_BASE}/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function updateAgent(id: string, body: AgentUpdate): Promise<AgentRecord> {
  const res = await fetch(`${API_BASE}/agents/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function deleteAgent(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/agents/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await parseApiError(res));
}

export async function fetchTools(): Promise<ToolRecord[]> {
  const res = await fetch(`${API_BASE}/tools`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = await res.json();
  return data.tools ?? [];
}

export async function fetchFactors(): Promise<FactorRecord[]> {
  const res = await fetch(`${API_BASE}/factors`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = await res.json();
  return data.factors ?? [];
}

export async function createFactor(body: FactorCreate): Promise<FactorRecord> {
  const res = await fetch(`${API_BASE}/factors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function updateFactor(id: string, body: FactorUpdate): Promise<FactorRecord> {
  const res = await fetch(`${API_BASE}/factors/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function deleteFactor(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/factors/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await parseApiError(res));
}

export async function evalFactor(body: {
  factor_id?: string;
  formula?: string;
  use_synthetic?: boolean;
}): Promise<FactorEvalResult> {
  const res = await fetch(`${API_BASE}/factors/eval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function startLlmMine(
  body: FactorMineLlmRequest,
): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/factors/mine/llm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function startGpMine(
  body: FactorMineGpRequest,
): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/factors/mine/gp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function synthesizeFactors(
  body: FactorSynthesizeRequest,
): Promise<FactorSynthesizeResult> {
  const res = await fetch(`${API_BASE}/factors/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function fetchFactorRun(runId: string): Promise<FactorMineRun> {
  const res = await fetch(`${API_BASE}/factors/runs/${runId}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function revalidatePaperFactors(body?: {
  factor_ids?: string[];
  lookback?: number;
}): Promise<{ count: number; results: Array<{ id: string; status?: string; error?: string }> }> {
  const res = await fetch(`${API_BASE}/factors/paper/revalidate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function runFactorScreen(body: FactorScreenRequest): Promise<FactorScreenResult> {
  const res = await fetch(`${API_BASE}/factors/screen`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function applyFactorScreen(
  body: FactorScreenApplyRequest,
): Promise<{ portfolio_id: string; name: string; member_count: number }> {
  const res = await fetch(`${API_BASE}/factors/screen/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}
