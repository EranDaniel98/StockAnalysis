/**
 * Server-side fetcher for the momentum-value "biggest-risers" book picks.
 * GET /api/research/momval-picks — read-only daily picks (momentum 0.6 /
 * value 0.4, quality+PEAD dropped), tuned for upside precision at 3-6mo.
 */

export type MomvalPick = {
  rank: number | null;
  ticker: string;
  composite_z: number | null;
  mom_rank: number | null;
  val_rank: number | null;
  sector: string | null;
};

export type MomvalPicks = {
  strategy: string;
  label: string;
  as_of: string;
  weights: Record<string, number>;
  factors_used: string[];
  universe_size: number;
  top_n: number;
  horizon_note: string;
  picks: MomvalPick[];
  generated_at: string;
};

export async function fetchMomvalPicks(): Promise<MomvalPicks | null> {
  const base = process.env.NEXT_INTERNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${base}/api/research/momval-picks`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as MomvalPicks;
  } catch {
    return null;
  }
}
