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
export type PortfolioRecommendations = Schemas["PortfolioRecommendations"];
export type PositionRecommendation = Schemas["PositionRecommendation"];
// PositionStatus is a Python Literal[...] alias — Pydantic doesn't promote
// those to top-level schemas, so we mirror the union locally. Keep in sync
// with src/api/routers/portfolio.py::PositionStatus.
export type PositionStatus =
  | "HOLDING"
  | "STOP_HIT"
  | "NEAR_STOP"
  | "TARGET_HIT"
  | "NEAR_TARGET";
export type PaperVsSpySnapshot = Schemas["PaperVsSpySnapshot"];
export type PipelineRecentResponse = Schemas["PipelineRecentResponse"];
export type PipelineRecentRun = Schemas["PipelineRecentRun"];
export type TodayActionsResponse = Schemas["TodayActionsResponse"];
export type TodayActionItem = Schemas["TodayActionItem"];
export type FactorBacktestSummary = Schemas["FactorBacktestSummary"];
export type FactorBacktestDetail = Schemas["FactorBacktestDetail"];
export type WalkForwardFold = Schemas["WalkForwardFold"];
export type IcReportSummary = Schemas["IcReportSummary"];
export type IcReportDetail = Schemas["IcReportDetail"];
export type IcFactorRow = Schemas["IcFactorRow"];
export type IcCellMetrics = Schemas["IcCellMetrics"];
export type ExecutionSummary = Schemas["ExecutionSummary"];
export type ExecutionDetail = Schemas["ExecutionDetail"];
export type SubmittedOrder = Schemas["SubmittedOrder"];
export type SkippedOrder = Schemas["SkippedOrder"];
export type FailedOrder = Schemas["FailedOrder"];
export type SanityGate = Schemas["SanityGate"];
export type SanityGateOutcome = Schemas["SanityGateOutcome"];

// ScanRequest / ScanResponse / ScanSummary / ScanResultItem /
// SanityCheckTriggerRequest were removed 2026-05-23 along with the
// legacy 5-engine endpoints they typed.
export type BuySignal = Schemas["BuySignal"];
export type SanityCheck = Schemas["SanityCheck"];
export type RiskManagement = Schemas["RiskManagement"];
export type StopLoss = Schemas["StopLoss"];
export type TakeProfit = Schemas["TakeProfit"];
export type TimeStop = Schemas["TimeStop"];
export type PositionSizing = Schemas["PositionSizing"];

// BacktestRequest/Response/Summary + DiagnosticRequest/Response/Summary
// removed 2026-05-23 with the /api/backtests + /api/diagnostics routes.

export type PaperRecommendationItem = Schemas["PaperRecommendationItem"];

export type StockDetail = Schemas["StockDetail"];
export type OHLCBar = Schemas["OHLCBar"];

export type MarketRegime = Schemas["MarketRegime"];
export type SectorsResponse = Schemas["SectorsResponse"];
export type SectorMetric = Schemas["SectorMetric"];
export type DashboardResponse = Schemas["DashboardResponse"];
export type DashboardPick = Schemas["DashboardPick"];
export type StrategyCard = Schemas["StrategyCard"];

export type BriefingResponse = Schemas["BriefingResponse"];
export type FactorCoverage = Schemas["FactorCoverage"];
export type TopPick = Schemas["TopPick"];
export type ActionCounts = Schemas["ActionCounts"];
export type DriftCheckOut = Schemas["DriftCheckOut"];
export type PositionAlert = Schemas["PositionAlert"];

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
      includeSpy?: boolean;
    }) => {
      const q = new URLSearchParams();
      if (params?.period) q.set("period", params.period);
      if (params?.timeframe) q.set("timeframe", params.timeframe);
      if (params?.includeSpy) q.set("include_spy", "true");
      const qs = q.toString();
      return request<PortfolioHistory>(
        `/api/portfolio/history${qs ? `?${qs}` : ""}`,
      );
    },
    recommendations: () =>
      request<PortfolioRecommendations>("/api/portfolio/recommendations"),
    spySnapshot: () =>
      request<PaperVsSpySnapshot>("/api/portfolio/spy-snapshot"),
  },

  scans: {
    // POST /api/scans, GET /api/scans, GET /api/scans/{id},
    // /latest-buys, /sanity-check were deleted 2026-05-23. They
    // drove the legacy 5-engine composite path which the FE no
    // longer consumes; the only remaining surface is the factor
    // pipeline's picks reader below.
    factorPicks: () => request<BuySignal[]>("/api/scans/factor-picks"),
  },

  executions: {
    list: (limit?: number) => {
      const q = new URLSearchParams();
      if (limit) q.set("limit", String(limit));
      const qs = q.toString();
      return request<ExecutionSummary[]>(
        `/api/executions${qs ? `?${qs}` : ""}`,
      );
    },
    get: (date: string) =>
      request<ExecutionDetail>(`/api/executions/${encodeURIComponent(date)}`),
  },

  icReports: {
    list: (limit?: number) => {
      const q = new URLSearchParams();
      if (limit) q.set("limit", String(limit));
      const qs = q.toString();
      return request<IcReportSummary[]>(
        `/api/ic-reports${qs ? `?${qs}` : ""}`,
      );
    },
    get: (slug: string) =>
      request<IcReportDetail>(`/api/ic-reports/${encodeURIComponent(slug)}`),
  },

  factorBacktests: {
    list: (params?: { kind?: "sweep" | "ab"; limit?: number }) => {
      const q = new URLSearchParams();
      if (params?.kind) q.set("kind", params.kind);
      if (params?.limit) q.set("limit", String(params.limit));
      const qs = q.toString();
      return request<FactorBacktestSummary[]>(
        `/api/factor-backtests${qs ? `?${qs}` : ""}`,
      );
    },
    get: (slug: string) =>
      request<FactorBacktestDetail>(
        `/api/factor-backtests/${encodeURIComponent(slug)}`,
      ),
  },

  pipeline: {
    recent: (limit?: number) => {
      const q = new URLSearchParams();
      if (limit) q.set("limit", String(limit));
      const qs = q.toString();
      return request<PipelineRecentResponse>(
        `/api/pipeline/recent${qs ? `?${qs}` : ""}`,
      );
    },
    todayActions: (picksDate?: string) => {
      const q = new URLSearchParams();
      if (picksDate) q.set("picks_date", picksDate);
      const qs = q.toString();
      return request<TodayActionsResponse>(
        `/api/pipeline/today-actions${qs ? `?${qs}` : ""}`,
      );
    },
  },

  // /api/backtests + /api/diagnostics were deleted 2026-05-23. The
  // FE never consumed them after the factor-pipeline migration; the
  // live backtest UI now uses api.factorBacktests (above) which reads
  // the on-disk reports.

  market: {
    regime: () => request<MarketRegime>("/api/market/regime"),
    sectors: () => request<SectorsResponse>("/api/market/sectors"),
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
    // POST /api/stocks/{ticker}/analyze was deleted 2026-05-23 — the
    // per-stock page now reads factor context from the basket basketItem
    // instead of running an on-demand 5-engine analyze.
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
    briefing: (params?: { picks_date?: string }) => {
      const qs = params?.picks_date ? `?picks_date=${params.picks_date}` : "";
      return request<BriefingResponse>(`/api/dashboard/briefing${qs}`);
    },
  },
};

export type Api = typeof api;
export type { paths };
