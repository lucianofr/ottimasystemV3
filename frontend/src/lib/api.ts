import type { components } from "./api-types";

export type LoginOut = components["schemas"]["LoginOut"];
export type UserOut = components["schemas"]["UserOut"];
export type ProjectOut = components["schemas"]["ProjectOut"];
export type ConnectionOut = components["schemas"]["ConnectionOut"];
export type ConnectionCreate = components["schemas"]["ConnectionCreate"];
export type ConnectionUpdate = components["schemas"]["ConnectionUpdate"];
export type CalculatedTagOut = components["schemas"]["CalculatedTagOut"];
export type CalculatedTagCreate = components["schemas"]["CalculatedTagCreate"];
export type CalculatedTagUpdate = components["schemas"]["CalculatedTagUpdate"];
export type TagOut = components["schemas"]["TagOut"];
export type TagCreate = components["schemas"]["TagCreate"];
export type TagUpdate = components["schemas"]["TagUpdate"];
export type FlowOut = components["schemas"]["FlowOut"];
export type FlowDetail = components["schemas"]["FlowDetail"];
export type FlowCreate = components["schemas"]["FlowCreate"];
export type FlowUpdate = components["schemas"]["FlowUpdate"];
export type FlowSaved = components["schemas"]["FlowSaved"];
export type EventOut = components["schemas"]["EventOut"];
export type HistoryResponse = components["schemas"]["HistoryResponse"];
export type HistorySeries = components["schemas"]["HistorySeries"];
export type MpcHistoryResponse = components["schemas"]["MpcHistoryResponse"];
export type MpcHistorySeries = components["schemas"]["MpcHistorySeries"];
export type HistoryRetentionOut = components["schemas"]["HistoryRetentionOut"];
export type HistoryRetentionUpdate = components["schemas"]["HistoryRetentionUpdate"];

const TOKEN_KEY = "ottima.token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    detail: string,
  ) {
    super(detail);
  }
}

export async function apiResposta(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && !path.endsWith("/auth/login")) {
    // interceptor global de sessão expirada (spec §8.5)
    clearToken();
    window.location.assign("/login");
    throw new ApiError(401, "Sessão expirada");
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = typeof body?.detail === "string" ? body.detail : "Erro inesperado";
    throw new ApiError(res.status, detail);
  }
  return res;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiResposta(path, init);
  // 204 (DELETE) e 202 sem corpo (deploy/parar, spec F3 §5.1) não trazem JSON para parsear.
  const corpo = await res.text();
  if (!corpo) return undefined as T;
  return JSON.parse(corpo) as T;
}
