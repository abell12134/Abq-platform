const API_BASE = "/api";

export async function parseApiError(res: Response): Promise<string> {
  const data = (await res.json().catch(() => ({}))) as { detail?: unknown; message?: unknown };
  const detail = data.detail ?? data.message;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        typeof item === "object" && item && "msg" in item
          ? String((item as { msg: string }).msg)
          : JSON.stringify(item),
      )
      .join("; ");
  }
  return `请求失败 (${res.status})`;
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res;
}

export { API_BASE };
