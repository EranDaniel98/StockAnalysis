/**
 * Typed fetch client over the StockNew FastAPI surface.
 *
 * Types come from `schema.ts` (generated via openapi-typescript from
 * api-openapi.json). Regenerate with `npm run gen:api` after every backend
 * shape change.
 */

import type { components, paths } from "./schema";

/**
 * API base URL.
 *
 * Resolution order:
 *   1. `NEXT_PUBLIC_API_URL` env (build-time bake-in for prod / overrides).
 *   2. In the browser, derive from `window.location.hostname:8000` so the
 *      page works the same whether opened at `localhost:3000`,
 *      `127.0.0.1:3000`, or `192.168.x.y:3000` from a phone on the LAN.
 *   3. SSR fallback: `127.0.0.1:8000`. Our queries don't run on the server
 *      (no HydrationBoundary), so this only matters if something inadvertently
 *      fetches during render.
 */
function resolveApiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined" && window.location?.hostname) {
    return `http://${window.location.hostname}:8000`;
  }
  return "http://127.0.0.1:8000";
}

export const API_BASE = resolveApiBase();

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
export type PortfolioHistory = Schemas["PortfolioHistory"];
export type EquityPoint = Schemas["EquityPoint"];

export type ScanRequest = Schemas["ScanRequest"];
export type ScanResponse = Schemas["ScanResponse"];
export type ScanSummary = Schemas["ScanSummary"];
export type ScanResultItem = Schemas["ScanResultItem"];
export type BuySignal = Schemas["BuySignal"];
export type SanityCheck = Schemas["SanityCheck"];
export type SanityCheckTriggerRequest = Schemas["SanityCheckTriggerRequest"];
export type RiskManagement = Schemas["RiskManagement"];
export type StopLoss = Schemas["StopLoss"];
export type TakeProfit = Schemas["TakeProfit"];
export type TimeStop = Schemas["TimeStop"];
export type PositionSizing = Schemas["PositionSizing"];

export type BacktestRequest = Schemas["BacktestRequest"];
export type BacktestResponse = Schemas["BacktestResponse"];
export type BacktestSummary = Schemas["BacktestSummary"];

export type DiagnosticRequest = Schemas["DiagnosticRequest"];
export type DiagnosticResponse = Schemas["DiagnosticResponse"];
export type DiagnosticSummary = Schemas["DiagnosticSummary"];

export type PaperRecommendationItem = Schemas["PaperRecommendationItem"];

export type StockDetail = Schemas["StockDetail"];
export type OHLCBar = Schemas["OHLCBar"];

export type MarketRegime = Schemas["MarketRegime"];
export type SectorsResponse = Schemas["SectorsResponse"];
export type SectorMetric = Schemas["SectorMetric"];
export type ScoreCalibration = Schemas["ScoreCalibration"];
export type CalibrationBucket = Schemas["CalibrationBucket"];
export type TradeAnalytics = Schemas["TradeAnalytics"];
export type TradeHeadline = Schemas["TradeHeadline"];
export type CumulativePnlPoint = Schemas["CumulativePnlPoint"];
export type ExitReasonStat = Schemas["ExitReasonStat"];
export type StrategyStat = Schemas["StrategyStat"];
export type HoldTimeBucket = Schemas["HoldTimeBucket"];
export type TickerStat = Schemas["TickerStat"];
export type PaperTradeItem = Schemas["PaperTradeItem"];
export type TradeNotesUpdate = Schemas["TradeNotesUpdate"];

export type MLModelsResponse = Schemas["MLModelsResponse"];
export type ModelVersionRow = Schemas["ModelVersionRow"];
export type ModelDriftSnapshot = Schemas["ModelDriftSnapshot"];
export type FoldMetric = Schemas["FoldMetric"];

export type DashboardResponse = Schemas["DashboardResponse"];
export type DashboardPick = Schemas["DashboardPick"];
export type StrategyCard = Schemas["StrategyCard"];

export type ResearchAskRequest = Schemas["ResearchAskRequest"];
export type ResearchRunSummary = Schemas["ResearchRunSummary"];
export type ResearchRunDetail = Schemas["ResearchRunDetail"];
export type ToolCallEntry = Schemas["ToolCallEntry"];
export type FilingNotificationItem = Schemas["FilingNotificationItem"];
export type SummarizeNotificationResponse = Schemas["SummarizeNotificationResponse"];

// ─── Endpoint helpers ────────────────────────────────────────────────────────

export const api = {
  health: () => request<{ status: string }>("/health"),
  ready: () =>
    request<{ status: string; db: string; redis: string }>("/health/ready"),

  portfolio: {
    status: () => request<PortfolioStatus>("/api/portfolio"),
    positions: () => request<Position[]>("/api/portfolio/positions"),
    account: () => request<AccountSummary>("/api/portfolio/account"),
    history: (params?: {
      period?: "1D" | "1W" | "1M" | "3M" | "6M" | "1A";
      timeframe?: "1Min" | "5Min" | "15Min" | "1H" | "1D";
    }) => {
      const q = new URLSearchParams();
      if (params?.period) q.set("period", params.period);
      if (params?.timeframe) q.set("timeframe", params.timeframe);
      const qs = q.toString();
      return request<PortfolioHistory>(
        `/api/portfolio/history${qs ? `?${qs}` : ""}`,
      );
    },
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
    latestBuys: (params?: { strongOnly?: boolean }) => {
      const q = new URLSearchParams();
      if (params?.strongOnly) q.set("strong_only", "true");
      const qs = q.toString();
      return request<BuySignal[]>(
        `/api/scans/latest-buys${qs ? `?${qs}` : ""}`,
      );
    },
    triggerSanityCheck: (body: SanityCheckTriggerRequest) =>
      request<BuySignal[]>("/api/scans/sanity-check", {
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
    tradesSummary: () =>
      request<TradeAnalytics>("/api/analytics/trades-summary"),
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

  research: {
    ask: (body: ResearchAskRequest) =>
      request<ResearchRunDetail>("/api/research/ask", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    list: (params?: { status?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.status) q.set("status", params.status);
      if (params?.limit != null) q.set("limit", String(params.limit));
      const qs = q.toString();
      return request<ResearchRunSummary[]>(
        `/api/research/runs${qs ? `?${qs}` : ""}`,
      );
    },
    get: (id: number, params?: { include_transcript?: boolean }) => {
      const q = new URLSearchParams();
      if (params?.include_transcript) q.set("include_transcript", "true");
      const qs = q.toString();
      return request<ResearchRunDetail>(
        `/api/research/runs/${id}${qs ? `?${qs}` : ""}`,
      );
    },
    notifications: (params?: { ticker?: string; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.ticker) q.set("ticker", params.ticker);
      if (params?.limit != null) q.set("limit", String(params.limit));
      const qs = q.toString();
      return request<FilingNotificationItem[]>(
        `/api/research/notifications${qs ? `?${qs}` : ""}`,
      );
    },
    summarizeNotification: (id: number) =>
      request<SummarizeNotificationResponse>(
        `/api/research/notifications/${id}/summarize`,
        { method: "POST" },
      ),
    monitorStatus: () =>
      request<{ running: boolean; poll_seconds: number; forms: string[] }>(
        "/api/research/monitor/status",
      ),
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

  stocks: {
    get: (ticker: string, params?: { history_days?: number }) => {
      const q = new URLSearchParams();
      if (params?.history_days != null) q.set("history_days", String(params.history_days));
      const qs = q.toString();
      return request<StockDetail>(
        `/api/stocks/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ""}`,
      );
    },
    /**
     * Run the full analyzer chain on a single ticker on-demand. Used as a
     * fallback when the ticker isn't present in any recent scan_run — keeps
     * the deep-dive page useful for arbitrary user input from the search bar.
     */
    analyze: (ticker: string, params?: { strategy?: string }) => {
      const q = new URLSearchParams();
      if (params?.strategy) q.set("strategy", params.strategy);
      const qs = q.toString();
      return request<ScanResultItem>(
        `/api/stocks/${encodeURIComponent(ticker)}/analyze${qs ? `?${qs}` : ""}`,
        { method: "POST" },
      );
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

  dashboard: {
    get: (params?: { top_n_per_strategy?: number; cross_strategy_top_n?: number }) => {
      const q = new URLSearchParams();
      if (params?.top_n_per_strategy != null)
        q.set("top_n_per_strategy", String(params.top_n_per_strategy));
      if (params?.cross_strategy_top_n != null)
        q.set("cross_strategy_top_n", String(params.cross_strategy_top_n));
      const qs = q.toString();
      return request<DashboardResponse>(
        `/api/dashboard${qs ? `?${qs}` : ""}`,
      );
    },
  },
};

export type Api = typeof api;
export type { paths };
