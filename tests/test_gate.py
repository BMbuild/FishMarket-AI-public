import json

import pandas as pd
import pytest

from fishmarket import loader
from fishmarket.config import DEFAULT
from fishmarket.trust import compute_trust
from helpers import gate_series

SINGLE = {("Wild salmon", "Pacific Northwest"), ("Sturgeon caviar", "Southeast")}


def test_clean_data_has_no_flags_except_single_source(ground_truth):
    assert len(ground_truth) == 64
    for key, v in ground_truth.items():
        g, _ = gate_series(v["species"], v["region"])
        want = {"single_source"} if v["single_source"] else set()
        assert g.flag_set() == want, key
        assert not g.hard_failure, key
        assert "outlier" not in g.flag_set()          # zero outlier flags on all clean data
        assert len(g.usable_ids) >= 1


def test_every_planted_case_matches_manifest(manifest, ground_truth):
    GATE_CASES = {"PP-STALE", "PP-UNIT", "PP-OUTLIER", "PP-CONFLICT", "PP-DUPMISS", "PP-RETAIL-OZ"}
    for case in [c for c in manifest if c["case_id"] in GATE_CASES]:
        ov = loader.overrides_from_manifest(DEFAULT, [case["case_id"]])
        changed = {}
        for key, v in ground_truth.items():
            g, _ = gate_series(v["species"], v["region"], ov)
            base, _ = gate_series(v["species"], v["region"])
            if g.flag_set() != base.flag_set():
                changed[key] = g
        by = case["expected_flags_by_series"]
        assert set(changed) == set(by), (case["case_id"], set(changed) ^ set(by))
        for key, g in changed.items():
            assert set(by[key]) <= g.flag_set(), (case["case_id"], key, g.flag_set())
            rating = compute_trust(g.flag_set(), g.usable_tiers())["rating"]
            assert rating == case["expected_trust_for_affected_series"], (case["case_id"], key, rating)


def test_kg_repair_matches_clean_within_half_a_percent():
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-UNIT"])
    fixed, _ = gate_series("Cod", "Northeast", ov, only={"SRC-GOV-01"})
    clean, _ = gate_series("Cod", "Northeast", only={"SRC-GOV-01"})
    assert fixed.sources["SRC-GOV-01"].flags["unit_mismatch"] == 6
    m = fixed.clean.merge(clean.clean, on="date", suffixes=("_f", "_c"))
    assert len(m) == len(clean.clean)
    assert ((m.price_f - m.price_c).abs() / m.price_c).max() < 0.005
    assert (fixed.clean["unit"] == "lb").all()


def test_outlier_month_is_removed():
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-OUTLIER"])
    g, _ = gate_series("Tilapia", "Southeast", ov, only={"SRC-GOV-02"})
    r = g.sources["SRC-GOV-02"]
    assert r.flags["outlier"] == 1
    assert "2026-04-01" not in set(r.clean["date"].dt.strftime("%Y-%m-%d"))
    clean, _ = gate_series("Tilapia", "Southeast", only={"SRC-GOV-02"})
    assert len(r.clean) == len(clean.clean) - 1


def test_dupmiss_leaves_no_duplicates_future_rows_or_invented_prices(manifest):
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-DUPMISS"])
    case = next(m for m in manifest if m["case_id"] == "PP-DUPMISS")
    raw = pd.read_csv(DEFAULT.DATA_DIR / case["file"], dtype=str, keep_default_na=False)
    for key in case["expected_flags_by_series"]:
        sp, rg = key.split("|")
        g, _ = gate_series(sp, rg, ov, only={"SRC-GOV-01"})
        d = g.sources["SRC-GOV-01"].clean
        assert not d.duplicated(["date"]).any()
        assert d["date"].max() <= pd.Timestamp("2026-10-15")
        assert d["price"].notna().all() and (d["price"] > 0).all()
        blank_price_months = raw[(raw.species == sp) & (raw.region == rg) & (raw.price == "")]["date"]
        assert not set(blank_price_months) & set(d["date"].dt.strftime("%Y-%m-%d"))   # skipped, not estimated


def test_stale_source_is_excluded_not_used(manifest):
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-STALE"])
    g, _ = gate_series("Cod", "Northeast", ov)
    assert "SRC-IND-01" not in g.usable_ids and "stale_data" in g.flag_set()


def test_conflict_names_the_pair():
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-CONFLICT"])
    g, _ = gate_series("Gulf shrimp", "Gulf", ov)
    assert g.disagreements and g.disagreements[0]["pair"] == ["SRC-GOV-01", "SRC-TRD-01"]


def test_blank_volume_in_price_only_source_is_not_an_error():
    g, _ = gate_series("Gulf shrimp", "Gulf")
    assert "missing_values" not in g.sources["SRC-TRD-01"].flags


def test_two_cases_replacing_the_same_source_are_rejected():
    with pytest.raises(ValueError):
        loader.overrides_from_manifest(DEFAULT, ["PP-UNIT", "PP-DUPMISS"])


def test_hard_failure_when_too_few_clean_months():
    g, reg = gate_series("Gulf shrimp", "Gulf", only={"SRC-GOV-01"})
    assert not g.hard_failure
    from dataclasses import replace
    from fishmarket import gate as G, loader as L
    from fishmarket.registry import load_catalog
    cfg2 = replace(DEFAULT, MIN_CLEAN_MONTHS=100)
    raws = L.load_all(cfg2, reg, None)
    g2 = G.run_gate(cfg2, reg, raws, ["SRC-GOV-01"], "Gulf shrimp", "Gulf", pd.Timestamp("2026-10-15"), load_catalog(cfg2))
    assert g2.hard_failure
