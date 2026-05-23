/**
 * TanStack Query key factory. Keep keys here so refetch/invalidate calls
 * don't drift between caller sites.
 */

export const qk = {
  health: ["health"] as const,
  ready: ["ready"] as const,

  portfolio: {
    all: ["portfolio"] as const,
    status: () => ["portfolio", "status"] as const,
    positions: () => ["portfolio", "positions"] as const,
    account: () => ["portfolio", "account"] as const,
    history: (params?: {
      period?: string; timeframe?: string; includeSpy?: boolean;
    }) => ["portfolio", "history", params ?? {}] as const,
    recommendations: () => ["portfolio", "recommendations"] as const,
    spySnapshot: () => ["portfolio", "spy-snapshot"] as const,
  },

  icReports: {
    all: ["ic-reports"] as const,
    list: (limit?: number) => ["ic-reports", "list", limit ?? 50] as const,
    detail: (slug: string) => ["ic-reports", "detail", slug] as const,
  },

  factorBacktests: {
    all: ["factor-backtests"] as const,
    list: (params?: { kind?: string; limit?: number }) =>
      ["factor-backtests", "list", params ?? {}] as const,
    detail: (slug: string) => ["factor-backtests", "detail", slug] as const,
  },

  pipeline: {
    all: ["pipeline"] as const,
    recent: (limit?: number) => ["pipeline", "recent", limit ?? 5] as const,
    todayActions: (picksDate?: string) =>
      ["pipeline", "today-actions", picksDate ?? "latest"] as const,
  },

  scans: {
    all: ["scans"] as const,
    list: (params?: { strategy?: string; limit?: number }) =>
      ["scans", "list", params ?? {}] as const,
    detail: (runId: string) => ["scans", "detail", runId] as const,
    latestBuys: (params?: { strongOnly?: boolean }) =>
      ["scans", "latest-buys", params ?? {}] as const,
    factorPicks: () => ["scans", "factor-picks"] as const,
  },

  backtests: {
    all: ["backtests"] as const,
    list: (params?: { strategy?: string; limit?: number }) =>
      ["backtests", "list", params ?? {}] as const,
    detail: (id: number) => ["backtests", "detail", id] as const,
  },

  diagnostics: {
    all: ["diagnostics"] as const,
    list: (params?: { factor?: string; limit?: number }) =>
      ["diagnostics", "list", params ?? {}] as const,
    detail: (id: number) => ["diagnostics", "detail", id] as const,
  },

  recommendations: {
    all: ["recommendations"] as const,
    list: (params?: {
      ticker?: string;
      strategy?: string;
      submitted_only?: boolean;
      limit?: number;
    }) => ["recommendations", "list", params ?? {}] as const,
  },

  stocks: {
    detail: (ticker: string, historyDays?: number) =>
      ["stocks", "detail", ticker.toUpperCase(), historyDays ?? null] as const,
  },

  dashboard: {
    get: (params?: { top_n_per_strategy?: number; cross_strategy_top_n?: number }) =>
      ["dashboard", params ?? {}] as const,
    briefing: (params?: { picks_date?: string }) =>
      ["dashboard", "briefing", params ?? {}] as const,
  },
} as const;
