"""Unit tests for the fundamental analyzer.

The analyzer is a pure function over a dict of metrics → ``{score,
scores, signals}``. We test the boundaries between buckets so a future
tweak to a threshold doesn't silently shift a strong-buy into a hold.

``config`` is the project's real ``Config`` (just gives us
``fundamental_filters`` defaults). Reading the YAML once is fast.
"""

from __future__ import annotations

import pytest

from src.config_loader import Config
from src.scoring.analyzers import fundamental


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config()


def _scores_only(fund: dict, cfg: Config) -> dict:
    """Run analyze() and return just the per-category score dict.
    Convenience to keep tests focused on the numbers, not the signal text."""
    return fundamental.analyze(fund, cfg)["scores"]


class TestEmptyInput:
    def test_empty_dict_returns_neutral(self, cfg: Config) -> None:
        result = fundamental.analyze({}, cfg)
        assert result["score"] == 50
        assert result["scores"] == {}
        assert result["signals"] == []

    def test_none_returns_error_marker(self, cfg: Config) -> None:
        result = fundamental.analyze(None, cfg)
        assert result["score"] == 50
        assert "error" in result


class TestValuationScore:
    def test_low_pe_scores_high(self, cfg: Config) -> None:
        scores = _scores_only({"pe_trailing": 10.0}, cfg)
        assert scores["valuation"] is not None
        assert scores["valuation"] >= 75

    def test_high_pe_scores_low(self, cfg: Config) -> None:
        scores = _scores_only({"pe_trailing": 80.0}, cfg)
        assert scores["valuation"] is not None
        assert scores["valuation"] <= 30

    def test_undervalued_peg_signals_bullish(self, cfg: Config) -> None:
        result = fundamental.analyze({"peg_ratio": 0.7}, cfg)
        signals = [s for s in result["signals"] if s.get("source") == "PEG"]
        assert signals and signals[0]["type"] == "bullish"

    def test_skips_negative_pe(self, cfg: Config) -> None:
        """Negative P/E (loss-making) is ignored, not penalized — the
        analyzer skips the metric rather than fabricating a number."""
        result = fundamental.analyze({"pe_trailing": -5.0}, cfg)
        # No valuation metrics → valuation bucket is None
        assert result["scores"].get("valuation") is None

    def test_falls_back_to_forward_pe(self, cfg: Config) -> None:
        scores = _scores_only({"pe_forward": 12.0}, cfg)
        assert scores["valuation"] is not None and scores["valuation"] >= 75


class TestGrowthScore:
    def test_strong_growth_scores_high(self, cfg: Config) -> None:
        scores = _scores_only(
            {"revenue_growth": 0.6, "earnings_growth": 0.55}, cfg
        )
        # Top bucket starts at >0.5
        assert scores["growth"] is not None and scores["growth"] >= 80

    def test_negative_growth_flags_bearish(self, cfg: Config) -> None:
        result = fundamental.analyze(
            {"revenue_growth": -0.1, "earnings_growth": -0.05}, cfg
        )
        bearish_sources = {s["source"] for s in result["signals"] if s["type"] == "bearish"}
        assert "Revenue" in bearish_sources
        assert "Earnings" in bearish_sources


class TestCompositeBehavior:
    def test_present_categories_redistribute_missing_weights(
        self, cfg: Config
    ) -> None:
        """When growth/health/etc are missing, the composite shouldn't
        collapse — present categories' weights renormalize."""
        result = fundamental.analyze({"pe_trailing": 10.0}, cfg)
        # Only valuation is present; composite should ≈ valuation score
        v = result["scores"]["valuation"]
        assert abs(result["score"] - v) < 0.1

    def test_composite_is_weighted_combination(self, cfg: Config) -> None:
        fund = {
            "pe_trailing": 10.0,            # valuation ≈ 80
            "revenue_growth": 0.6,          # growth ≈ 90
            "profit_margins": 0.30,         # profitability strong
            "debt_to_equity": 0.20,         # health strong
        }
        result = fundamental.analyze(fund, cfg)
        # All four are above the neutral 50 → composite well into bullish.
        assert result["score"] >= 65


class TestProfitabilityScore:
    def test_excellent_roe_flags_bullish(self, cfg: Config) -> None:
        result = fundamental.analyze({"roe": 0.30}, cfg)
        sources = {s["source"] for s in result["signals"] if s["type"] == "bullish"}
        assert "ROE" in sources

    def test_negative_roe_flags_bearish(self, cfg: Config) -> None:
        result = fundamental.analyze({"roe": -0.05}, cfg)
        sources = {s["source"] for s in result["signals"] if s["type"] == "bearish"}
        assert "ROE" in sources

    def test_strong_margins_drive_high_profitability_score(self, cfg: Config) -> None:
        scores = _scores_only(
            {"profit_margin": 0.35, "operating_margin": 0.32, "gross_margins": 0.65},
            cfg,
        )
        assert scores["profitability"] is not None
        assert scores["profitability"] >= 75


class TestHealthScore:
    def test_low_debt_flags_bullish(self, cfg: Config) -> None:
        result = fundamental.analyze({"debt_to_equity": 0.15}, cfg)
        sources = {s["source"] for s in result["signals"] if s["type"] == "bullish"}
        assert "Debt" in sources

    def test_high_debt_flags_bearish(self, cfg: Config) -> None:
        # yfinance often reports D/E as a percentage; the analyzer normalizes
        # values >10 by dividing by 100. So 350 means 3.5x.
        result = fundamental.analyze({"debt_to_equity": 350.0}, cfg)
        sources = {s["source"] for s in result["signals"] if s["type"] == "bearish"}
        assert "Debt" in sources

    def test_negative_fcf_flags_bearish(self, cfg: Config) -> None:
        result = fundamental.analyze({"free_cash_flow": -5_000_000}, cfg)
        sources = {s["source"] for s in result["signals"] if s["type"] == "bearish"}
        assert "FCF" in sources

    def test_low_current_ratio_flags_bearish(self, cfg: Config) -> None:
        result = fundamental.analyze({"current_ratio": 0.3}, cfg)
        sources = {s["source"] for s in result["signals"] if s["type"] == "bearish"}
        assert "Liquidity" in sources


class TestDividendScore:
    def test_zero_dividend_yields_none(self, cfg: Config) -> None:
        """Growth stocks pay no dividend; the bucket should be skipped
        entirely so it doesn't penalize the composite."""
        result = fundamental.analyze({"dividend_yield": 0}, cfg)
        assert result["scores"].get("dividend") is None

    def test_implausible_yield_is_treated_as_bad_data(self, cfg: Config) -> None:
        """yfinance occasionally returns malformed yields (>25%). The
        analyzer rejects rather than fabricating a bullish signal."""
        result = fundamental.analyze({"dividend_yield": 0.45}, cfg)
        assert result["scores"].get("dividend") is None

    def test_high_yield_flags_bullish(self, cfg: Config) -> None:
        result = fundamental.analyze({"dividend_yield": 0.06, "payout_ratio": 0.4}, cfg)
        sources = {s["source"] for s in result["signals"] if s["type"] == "bullish"}
        assert "Dividend" in sources

    def test_unsustainable_payout_flags_bearish(self, cfg: Config) -> None:
        result = fundamental.analyze({"dividend_yield": 0.04, "payout_ratio": 0.9}, cfg)
        sources = {s["source"] for s in result["signals"] if s["type"] == "bearish"}
        assert "Dividend" in sources


class TestSectorRelativeValuation:
    """Sector-relative scoring is the #3 deferred improvement. The
    legacy absolute-threshold path (P/E < 15 → 80) penalizes high-
    multiple sectors uniformly; sector-relative scoring compares
    against the cohort median so 'cheap for software' beats 'expensive
    for utilities'."""

    @pytest.fixture
    def tech_stats(self) -> dict:
        # Tech P/E cohort skews high; q1=25, median=35, q3=45.
        return {
            "Technology": {
                "pe_trailing": {"q1": 25.0, "median": 35.0, "q3": 45.0, "count": 10.0},
                "pb_ratio": {"q1": 3.0, "median": 5.0, "q3": 8.0, "count": 10.0},
            }
        }

    def test_pe_30_is_neutral_for_tech(self, cfg, tech_stats: dict) -> None:
        """P/E 30 is below tech median (35) → 'below_median' → 65.
        Under the absolute path, 30 would have scored 50."""
        result = fundamental.analyze(
            {"sector": "Technology", "pe_trailing": 30.0},
            cfg, sector_stats=tech_stats,
        )
        assert result["scores"]["valuation"] == 65

    def test_pe_20_is_bullish_for_tech(self, cfg, tech_stats: dict) -> None:
        """P/E 20 is below tech Q1 (25) → 'low' → 80. Cheap for tech."""
        result = fundamental.analyze(
            {"sector": "Technology", "pe_trailing": 20.0},
            cfg, sector_stats=tech_stats,
        )
        assert result["scores"]["valuation"] >= 75
        bullish_sources = {s["source"] for s in result["signals"] if s["type"] == "bullish"}
        assert "P/E vs Sector" in bullish_sources

    def test_pe_50_is_bearish_for_tech(self, cfg, tech_stats: dict) -> None:
        """P/E 50 is above tech Q3 (45) → 'high' → 30."""
        result = fundamental.analyze(
            {"sector": "Technology", "pe_trailing": 50.0},
            cfg, sector_stats=tech_stats,
        )
        assert result["scores"]["valuation"] <= 35
        bearish_sources = {s["source"] for s in result["signals"] if s["type"] == "bearish"}
        assert "P/E vs Sector" in bearish_sources

    def test_falls_back_to_absolute_when_sector_missing(
        self, cfg, tech_stats: dict
    ) -> None:
        """Healthcare isn't in the sector_stats dict; analyzer must
        fall back to absolute thresholds. P/E 10 → absolute 'Low P/E'
        → 80."""
        result = fundamental.analyze(
            {"sector": "Healthcare", "pe_trailing": 10.0},
            cfg, sector_stats=tech_stats,
        )
        assert result["scores"]["valuation"] >= 75
        sources = {s["source"] for s in result["signals"] if s["type"] == "bullish"}
        # Legacy signal label, not the sector-relative one.
        assert "P/E" in sources
        assert "P/E vs Sector" not in sources

    def test_falls_back_when_sector_stats_none(self, cfg) -> None:
        """Passing sector_stats=None reproduces the legacy behavior
        exactly — protects callers that haven't been migrated yet."""
        result_with = fundamental.analyze(
            {"sector": "Technology", "pe_trailing": 10.0},
            cfg, sector_stats=None,
        )
        result_without = fundamental.analyze(
            {"sector": "Technology", "pe_trailing": 10.0},
            cfg,
        )
        assert result_with["scores"]["valuation"] == result_without["scores"]["valuation"]

    def test_partial_sector_coverage_mixes_modes(self, cfg) -> None:
        """Only P/E has sector stats; PEG falls back to absolute.
        Both should contribute to the valuation score."""
        stats = {
            "Technology": {
                "pe_trailing": {"q1": 25.0, "median": 35.0, "q3": 45.0, "count": 10.0},
            }
        }
        result = fundamental.analyze(
            {"sector": "Technology", "pe_trailing": 20.0, "peg_ratio": 0.5},
            cfg, sector_stats=stats,
        )
        # Both metrics scored: 80 (sector-relative P/E 'low') + 85 (absolute PEG).
        assert result["scores"]["valuation"] is not None
        sources = {s["source"] for s in result["signals"]}
        assert "P/E vs Sector" in sources
        assert "PEG" in sources  # absolute fallback


class TestAnalystScore:
    def test_no_recommendation_yields_none(self, cfg: Config) -> None:
        assert _scores_only({}, cfg).get("analyst") is None

    def test_known_recommendation_keys_map_to_score(self, cfg: Config) -> None:
        # Direct from the score_map dict in _score_analyst.
        for key, expected_floor in [
            ("strongBuy", 80),
            ("buy", 70),
            ("hold", 45),
            ("sell", 20),
            ("strongSell", 5),
        ]:
            result = _scores_only({"recommendation": key}, cfg)
            assert result["analyst"] is not None
            if key in ("strongBuy", "buy"):
                assert result["analyst"] >= expected_floor
            elif key == "hold":
                assert 40 <= result["analyst"] <= 60
            else:
                assert result["analyst"] <= 30
