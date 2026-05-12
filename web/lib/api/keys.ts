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
  },

  scans: {
    all: ["scans"] as const,
    list: (params?: { strategy?: string; limit?: number }) =>
      ["scans", "list", params ?? {}] as const,
    detail: (runId: string) => ["scans", "detail", runId] as const,
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
} as const;
