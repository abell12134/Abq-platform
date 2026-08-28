import type {
  PortfolioMember,
  PortfolioRecord,
  PortfolioSnapshot,
  PortfolioUpdateBody,
  TrackRecord,
} from "../types/portfolio";
import { API_BASE, parseApiError } from "./http";

export async function fetchPortfolios(): Promise<PortfolioRecord[]> {
  const res = await fetch(`${API_BASE}/portfolios`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = await res.json();
  return data.portfolios ?? [];
}

export async function fetchPortfolio(portfolioId: string): Promise<PortfolioRecord> {
  const res = await fetch(`${API_BASE}/portfolios/${portfolioId}`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function fetchPortfolioSnapshot(portfolioId: string): Promise<PortfolioSnapshot> {
  const res = await fetch(`${API_BASE}/portfolios/${portfolioId}/snapshot`);
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function fetchPortfolioTracks(portfolioId: string): Promise<TrackRecord[]> {
  const res = await fetch(`${API_BASE}/portfolios/${portfolioId}/tracks`);
  if (!res.ok) throw new Error(await parseApiError(res));
  const data = await res.json();
  return data.records ?? [];
}

export async function recordPortfolioTrack(
  portfolioId: string,
  body?: { note?: string; path_id?: string },
): Promise<TrackRecord> {
  const res = await fetch(`${API_BASE}/portfolios/${portfolioId}/track`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function updatePortfolio(
  portfolioId: string,
  body: PortfolioUpdateBody,
): Promise<PortfolioRecord> {
  const res = await fetch(`${API_BASE}/portfolios/${portfolioId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function createPortfolio(body: {
  id: string;
  name: string;
  members?: PortfolioMember[];
}): Promise<PortfolioRecord> {
  const res = await fetch(`${API_BASE}/portfolios`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ realm: "a-share", members: [], ...body }),
  });
  if (!res.ok) throw new Error(await parseApiError(res));
  return res.json();
}

export async function deletePortfolio(portfolioId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/portfolios/${portfolioId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await parseApiError(res));
}
