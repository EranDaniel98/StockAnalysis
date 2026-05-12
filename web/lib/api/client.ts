/**
 * Typed fetch client over the StockNew FastAPI surface.
 *
 * Types come from `schema.ts` (generated via openapi-typescript from
 * api-openapi.json). Regenerate with `npm run gen:api` after every backend
 * shape change.
 */

import type { components, paths } from "./schema";

/** Default base URL — overridable via NEXT_PUBLIC_API_URL. */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `API ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // non-JSON error body — keep null
    }
    throw new ApiError(res.status, body, `${res.status} ${res.statusText}`);
  }
  // Routes that legitimately return no body (none in v1, but stay safe).
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ─── Shorthand entity aliases sourced from the generated schema ──────────────

type Schemas = components["schemas"];

export type AccountSummary = Schemas["AccountSummary"];
export type Position = Schemas["Position"];
export type PortfolioStatus = Schemas["PortfolioStatus"];

export type ScanRequest = Schemas["ScanRequest"];
export type ScanResponse = Schemas["ScanResponse"];
export type ScanSummary = Schemas["ScanSummary"];
export type ScanResultItem = Schemas["ScanResultItem"];

export type BacktestRequest = Schemas["BacktestRequest"];
export type BacktestResponse = Schemas["BacktestResponse"];
export type BacktestSummary = Schemas["BacktestSummary"];

export type DiagnosticRequest = Schemas["DiagnosticRequest"];
export type DiagnosticResponse = Schemas["DiagnosticResponse"];
export type DiagnosticSummary = Schemas["DiagnosticSummary"];

export type PaperRecommendationItem = Schemas["PaperRecommendationItem"];

export type MarketRegime = Schemas["MarketRegime"];
export type SectorsResponse = Schemas["SectorsResponse"];
export type SectorMetric = Schemas["SectorMetric"];
export type ScoreCalibration = Schemas["ScoreCalibration"];
export type CalibrationBucket = Schemas["CalibrationBucket"];
export type PaperTradeItem = Schemas["PaperTradeItem"];
export type TradeNotesUpdate = Schemas["TradeNotesUpdate"];

export type MLModelsResponse = Schemas["MLModelsResponse"];
export type ModelVersionRow = Schemas["ModelVersionRow"];
export type ModelDriftSnapshot = Schemas["ModelDriftSnapshot"];
export type FoldMetric = Schemas["FoldMetric"];

// ─── Endpoint helpers ────────────────────────────────────────────────────────

export const api = {
  health: () => request<{ status: string }>("/health"),
  ready: () =>
    request<{ status: string; db: string; redis: string }>("/health/ready"),

  portfolio: {
    status: () => request<PortfolioStatus>("/api/portfolio"),
    positions: () => request<Position[]>("/api/portfolio/positions"),
    account: () => request<AccountSummary>("/api/portfolio/account"),
  },

  scans: {
    list: (params?: { strategy?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.strategy) q.set("strategy", params.strategy);
      if (params?.limit) q.set("limit", String(params.limit));
      const qs = q.toString();
      return request<ScanSummary[]>(`/api/scans${qs ? `?${qs}` : ""}`);
    },
    get: (runId: string) =>
      request<ScanResponse>(`/api/scans/${encodeURIComponent(runId)}`),
    trigger: (body: ScanRequest) =>
      request<ScanResponse>("/api/scans", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  backtests: {
    list: (params?: { strategy?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.strategy) q.set("strategy", params.strategy);
      if (params?.limit) q.set("limit", String(params.limit));
      const qs = q.toString();
      return request<BacktestSummary[]>(`/api/backtests${qs ? `?${qs}` : ""}`);
    },
    get: (id: number) => request<BacktestResponse>(`/api/backtests/${id}`),
    trigger: (body: BacktestRequest) =>
      request<BacktestResponse>("/api/backtests", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  diagnostics: {
    list: (params?: { factor?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.factor) q.set("factor", params.factor);
      if (params?.limit) q.set("limit", String(params.limit));
      const qs = q.toString();
      return request<DiagnosticSummary[]>(
        `/api/diagnostics${qs ? `?${qs}` : ""}`,
      );
    },
    get: (id: number) => request<DiagnosticResponse>(`/api/diagnostics/${id}`),
    trigger: (body: DiagnosticRequest) =>
      request<DiagnosticResponse>("/api/diagnostics", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  market: {
    regime: () => request<MarketRegime>("/api/market/regime"),
    sectors: () => request<SectorsResponse>("/api/market/sectors"),
  },

  analytics: {
    calibration: (params?: { min_score?: number }) => {
      const q = new URLSearchParams();
      if (params?.min_score != null) q.set("min_score", String(params.min_score));
      const qs = q.toString();
      return request<ScoreCalibration>(
        `/api/analytics/calibration${qs ? `?${qs}` : ""}`,
      );
    },
  },

  trades: {
    list: (params?: {
      ticker?: string;
      min_score?: number;
      has_notes?: boolean;
      limit?: number;
    }) => {
      const q = new URLSearchParams();
      if (params?.ticker) q.set("ticker", params.ticker);
      if (params?.min_score != null) q.set("min_score", String(params.min_score));
      if (params?.has_notes != null) q.set("has_notes", String(params.has_notes));
      if (params?.limit != null) q.set("limit", String(params.limit));
      const qs = q.toString();
      return request<PaperTradeItem[]>(`/api/trades${qs ? `?${qs}` : ""}`);
    },
    updateNotes: (id: number, body: TradeNotesUpdate) =>
      request<PaperTradeItem>(`/api/trades/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
  },

  ml: {
    models: (params?: {
      model_name?: string;
      limit?: number;
      window_days?: number;
    }) => {
      const q = new URLSearchParams();
      if (params?.model_name) q.set("model_name", params.model_name);
      if (params?.limit != null) q.set("limit", String(params.limit));
      if (params?.window_days != null) q.set("window_days", String(params.window_days));
      const qs = q.toString();
      return request<MLModelsResponse>(`/api/ml/models${qs ? `?${qs}` : ""}`);
    },
  },

  recommendations: {
    list: (params?: {
      ticker?: string;
      strategy?: string;
      submitted_only?: boolean;
      limit?: number;
    }) => {
      const q = new URLSearchParams();
      if (params?.ticker) q.set("ticker", params.ticker);
      if (params?.strategy) q.set("strategy", params.strategy);
      if (params?.submitted_only) q.set("submitted_only", "true");
      if (params?.limit) q.set("limit", String(params.limit));
      const qs = q.toString();
      return request<PaperRecommendationItem[]>(
        `/api/recommendations${qs ? `?${qs}` : ""}`,
      );
    },
    get: (id: number) =>
      request<PaperRecommendationItem>(`/api/recommendations/${id}`),
  },
};

export type Api = typeof api;
export type { paths };
