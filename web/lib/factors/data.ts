/**
 * Server-only loaders for the factor-strategy daily artifacts.
 *
 * Reads JSON files written by the Python pipeline from
 * `data/daily_picks/` and `reports/` (relative to the repo root).
 * Designed for server components / route handlers — never import
 * from a `"use client"` file.
 *
 * Path resolution: the Python project root sits one level above
 * the web/ directory. We resolve relative to `process.cwd()` which
 * is `web/` when running `next dev`.
 */
import { promises as fs } from "node:fs";
import path from "node:path";

const REPO_ROOT = path.resolve(process.cwd(), "..");
const PICKS_DIR = path.join(REPO_ROOT, "data", "daily_picks");
const REPORTS_DIR = path.join(REPO_ROOT, "reports");
const PAPER_VS_SPY_FILE = path.join(REPORTS_DIR, "paper_vs_spy.json");

/** Per-pick row from `data/daily_picks/YYYY-MM-DD.json`. */
export type DailyPick = {
  rank: number;
  ticker: string;
  z_score: number;
  mean_normalized_rank?: number;
  raw?: number;
  mom_rank?: number | null;
  qual_rank?: number | null;
  val_rank?: number | null;
  pead_rank?: number | null;
  sector?: string | null;
};

export type DailyPicksFile = {
  as_of: string;
  generated_at_utc: string;
  strategy: string;
  universe_size: number;
  top_n: number;
  picks: DailyPick[];
  snapshot_id: string | null;
};

/** Per-pick analysis row from `reports/portfolio_analysis_*.json`. */
export type AnalysisPick = {
  rank: number;
  ticker: string;
  composite_z: number;
  entry_price: number;
  stop_loss: number;
  target: number;
  time_exit_date: string;
  target_shares: number;
  position_size_usd: number;
  expected_return_pct: number;
  rationale: string;
  analyst_target: number | null;
  sector: string | null;
  days_to_earnings: number | null;
};

export type AnalysisFile = {
  as_of: string;
  generated_at_utc: string;
  strategy: string | null;
  equity_usd: number;
  n_positions: number;
  expected_per_pick_pct: {
    median: number;
    p75: number;
    p25: number;
  };
  picks: AnalysisPick[];
};

/** Most-recent file in `data/daily_picks/` (by name; ISO date sorts). */
export async function findLatestPicksDate(): Promise<string | null> {
  try {
    const files = await fs.readdir(PICKS_DIR);
    const dates = files
      .filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f))
      .map((f) => f.replace(/\.json$/, ""))
      .sort();
    return dates.length > 0 ? dates[dates.length - 1] : null;
  } catch {
    return null;
  }
}

export async function loadPicks(
  date: string,
): Promise<DailyPicksFile | null> {
  const filePath = path.join(PICKS_DIR, `${date}.json`);
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    return JSON.parse(raw) as DailyPicksFile;
  } catch {
    return null;
  }
}

export async function loadAnalysis(
  date: string,
): Promise<AnalysisFile | null> {
  // Reports use underscored dates: 2026_05_16. Picks files use 2026-05-16.
  const dateUnderscored = date.replace(/-/g, "_");
  const filePath = path.join(
    REPORTS_DIR,
    `portfolio_analysis_${dateUnderscored}.json`,
  );
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    return JSON.parse(raw) as AnalysisFile;
  } catch {
    return null;
  }
}

/** Returns markdown body of a daily report file, or null if missing. */
export async function loadReportMarkdown(
  date: string,
  reportName:
    | "morning_briefing"
    | "exit_plan"
    | "stress_test"
    | "watchlist"
    | "position_monitor"
    | "portfolio_analysis",
): Promise<string | null> {
  const dateUnderscored = date.replace(/-/g, "_");
  const filePath = path.join(
    REPORTS_DIR,
    `${reportName}_${dateUnderscored}.md`,
  );
  try {
    return await fs.readFile(filePath, "utf-8");
  } catch {
    return null;
  }
}

/**
 * Live paper-vs-SPY P&L snapshot. Written by
 * `scripts/paper_vs_spy_snapshot.py` on every daily-pipeline run.
 * One file (not date-stamped) — we want "where do we stand right now"
 * not historical snapshots.
 *
 * ``status`` values:
 *   - "ok": data is real and comparable
 *   - "not_configured": Alpaca creds missing or invalid
 *   - "no_history": account exists but Alpaca returned no portfolio_history
 *   - "error": something else failed; FE shows the message
 */
export type PaperVsSpyStatus =
  | "ok"
  | "not_configured"
  | "no_history"
  | "error";

export type PaperVsSpyFile = {
  status: PaperVsSpyStatus;
  message?: string;
  generated_at_utc: string;
  window_days: number;
  paper?: {
    starting_equity_usd: number;
    current_equity_usd: number;
    pnl_usd: number;
    return_pct: number;
  };
  spy?: {
    starting_price: number;
    current_price: number;
    return_pct: number;
  };
  alpha_pct?: number;
};

export async function loadPaperVsSpy(): Promise<PaperVsSpyFile | null> {
  try {
    const raw = await fs.readFile(PAPER_VS_SPY_FILE, "utf-8");
    return JSON.parse(raw) as PaperVsSpyFile;
  } catch {
    return null;
  }
}

/** Per-pick verdict from `reports/ai_sanity_check_YYYY-MM-DD.json`. */
export type SanityVerdict = "KEEP" | "FLAG" | "VETO";

export type SanityPickRow = {
  ticker: string;
  verdict: SanityVerdict;
  reason: string;
  evidence: string;
};

export type SanityCheckFile = {
  as_of: string;
  generated_at_utc: string;
  model: string;
  verdict: {
    overall_verdict: string;
    confidence: number;
    key_concerns: string[];
    per_pick: SanityPickRow[];
  };
};

/**
 * Reads the AI sanity-check JSON for ``date``. File naming uses dashes
 * (``ai_sanity_check_2026-05-23.json``) — distinct from the underscored
 * convention used by ``portfolio_analysis_*.json``.
 */
export async function loadSanityCheck(
  date: string,
): Promise<SanityCheckFile | null> {
  const filePath = path.join(
    REPORTS_DIR,
    `ai_sanity_check_${date}.json`,
  );
  try {
    const raw = await fs.readFile(filePath, "utf-8");
    return JSON.parse(raw) as SanityCheckFile;
  } catch {
    return null;
  }
}

/**
 * Reads yesterday's picks file (or the most-recent prior date) so the
 * page can mark which of today's tickers carried over via hysteresis.
 * Returns null when no prior file exists; callers should treat that as
 * "every pick is new" without erroring.
 */
export async function loadPreviousPicks(
  todayDate: string,
): Promise<DailyPicksFile | null> {
  try {
    const files = await fs.readdir(PICKS_DIR);
    const priorDates = files
      .filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f))
      .map((f) => f.replace(/\.json$/, ""))
      .filter((d) => d < todayDate)
      .sort();
    const last = priorDates[priorDates.length - 1];
    return last ? loadPicks(last) : null;
  } catch {
    return null;
  }
}

/** Briefing-endpoint shape — subset used by the /factors page. The
 *  fields below are the only ones we read; the API may return more. */
export type BriefingFromApi = {
  picks_date: string | null;
  gate_status: "ok" | "warn" | "fail" | "no_picks";
  paper_equity_usd: number | null;
  action_counts: {
    n_new_buys: number;
    n_keep: number;
    n_exit: number;
    new_buy_tickers: string[];
    keep_tickers: string[];
    exit_tickers: string[];
  } | null;
};

/**
 * Server-side fetch of /api/dashboard/briefing. Used by server
 * components that need the live held/new-buy/exit ticker lists without
 * round-tripping through Alpaca themselves.
 *
 * Returns null on any failure (FastAPI down, non-2xx, parse error) so
 * callers can degrade gracefully — the page still renders, just without
 * held/carry indicators.
 */
export async function fetchBriefingServer(): Promise<BriefingFromApi | null> {
  const base = process.env.NEXT_INTERNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${base}/api/dashboard/briefing`, {
      // Server components default-cache; we want fresh every request.
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as BriefingFromApi;
  } catch {
    return null;
  }
}

/** Pre-built sector breakdown from an analysis file. */
export function sectorCounts(
  analysis: AnalysisFile,
): { sector: string; count: number; pct: number }[] {
  const counts = new Map<string, number>();
  for (const p of analysis.picks) {
    const s = p.sector ?? "Unknown";
    counts.set(s, (counts.get(s) ?? 0) + 1);
  }
  const total = analysis.picks.length || 1;
  return Array.from(counts.entries())
    .map(([sector, count]) => ({
      sector,
      count,
      pct: (100 * count) / total,
    }))
    .sort((a, b) => b.count - a.count);
}
