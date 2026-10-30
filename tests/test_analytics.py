import pandas as pd
import pytest

from fishmarket.analytics import compute_stats, stat_by_kind
from helpers import AS_OF, gate_series


def test_stats_match_ground_truth_for_all_17_series(ground_truth):
    for key, gt in ground_truth.items():
        g, _ = gate_series(gt["species"], gt["region"])
        out = compute_stats(g.clean, key, g.primary_id, AS_OF)
        st = out["stats"]
        idx = out["seasonal_index"]
        assert max(abs(a - b) for a, b in zip(idx, gt["measured_seasonal_price_index"])) < 0.002, key
        assert abs(stat_by_kind(st, "best_next3_vs_now_ratio").value - gt["measured_best_next3_vs_now_ratio"]) < 0.002, key
        assert abs(stat_by_kind(st, "yoy_price_change_pct").value - gt["measured_yoy_price_change_pct"]) < 0.05, key
        assert abs(stat_by_kind(st, "supply_yoy_change_pct").value - gt["measured_supply_yoy_last3_pct"]) < 0.05, key
        peak = stat_by_kind(st, "seasonal_peak_month")
        if gt["seasonality_strength"] == "strong":
            assert peak.reliability == "strong" and peak.month == gt["planted_peak_price_month"], key
        else:
            assert peak.reliability == "weak", key


def test_stat_ids_are_sequential_and_unique():
    g, _ = gate_series("Cod", "Northeast")
    ids = [s.id for s in compute_stats(g.clean, "x", "SRC-GOV-01", AS_OF)["stats"]]
    assert ids == [f"S{i}" for i in range(1, len(ids) + 1)]


def test_no_complete_year_means_no_seasonal_stats():
    g, _ = gate_series("Cod", "Northeast")
    short = g.clean[g.clean["date"] >= "2026-01-01"]
    kinds = {s.kind for s in compute_stats(short, "x", "S", AS_OF)["stats"]}
    assert "best_next3_vs_now_ratio" not in kinds and "latest_price" in kinds


def test_yoy_unavailable_with_too_few_observations():
    g, _ = gate_series("Cod", "Northeast")
    short = g.clean.tail(14)
    kinds = {s.kind for s in compute_stats(short, "x", "S", AS_OF)["stats"]}
    assert "yoy_price_change_pct" not in kinds


def test_price_only_primary_has_no_supply_stat():
    g, _ = gate_series("Gulf shrimp", "Gulf", only={"SRC-TRD-01"})
    kinds = {s.kind for s in compute_stats(g.clean, "x", "SRC-TRD-01", AS_OF)["stats"]}
    assert "supply_yoy_change_pct" not in kinds
