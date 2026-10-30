"""Unit tests for the new question-type rules, extras, planted v2 cases and repo hygiene."""
import re
import pandas as pd
import pytest

from fishmarket import extras, loader
from fishmarket.config import DEFAULT, ROOT
from fishmarket.extras import Extras
from fishmarket.fake_agents import fake_llm
from fishmarket.pipeline import ProfileError, build_brief, run
from fishmarket.questions import _direction
from fishmarket.schemas import StatRow

AS_OF = pd.Timestamp("2026-10-15")


def S(kind, v):
    return StatRow(id="S1", series="a|b", kind=kind, value=v, unit="x")


@pytest.mark.parametrize("v,want", [(1.10, "hold"), (1.0999, "sell_now"), (1.5, "hold")])
def test_sell_or_hold_threshold(v, want):
    assert _direction([S("best_next3_vs_now_ratio", v)], "sell_or_hold", DEFAULT) == want


@pytest.mark.parametrize("v,want", [(1.05, "buy_now"), (1.049, "no_clear_signal"), (0.95, "wait"), (0.951, "no_clear_signal"), (0.5, "wait")])
def test_buy_now_or_wait_thresholds(v, want):
    assert _direction([S("next3_mean_vs_now_ratio", v)], "buy_now_or_wait", DEFAULT) == want


def test_ranking_types_have_ranking_direction_or_insufficient():
    assert _direction([S("market_net_price", 3.0)], "compare_markets", DEFAULT) == "ranking"
    assert _direction([], "best_months", DEFAULT) == "insufficient_data"


def test_quality_status_rules_and_notes_are_scanned():
    ex = Extras(DEFAULT)
    q = ex.quality_summary("Cod", "Northeast", AS_OF)
    assert q["status"] == "verified" and q["injection_phrases"] == []
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-QUAL-UNVERIFIED"])
    assert Extras(DEFAULT, ov).quality_summary("Cod", "Northeast", AS_OF)["status"] == "unverified"
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-QUAL-INJECT"])
    q = Extras(DEFAULT, ov).quality_summary("Cod", "Northeast", AS_OF)
    assert "untrusted_text_ignored" in q["flags"] and q["injection_phrases"]


def test_market_stale_is_excluded_and_cad_is_converted():
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-MKT-STALE"])
    cm = Extras(DEFAULT, ov).market_comparison("Walleye", "Great Lakes", AS_OF)
    assert [r["market_id"] for r in cm["excluded"]] == ["MKT-GL-02"] and "stale_data" in cm["flags"]
    clean = Extras(DEFAULT).market_comparison("Pacific halibut", "Alaska", AS_OF)
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-MKT-CAD"])
    cad = Extras(DEFAULT, ov).market_comparison("Pacific halibut", "Alaska", AS_OF)
    assert "currency_mismatch" in cad["flags"]
    a = {r["market_id"]: r["mean3_price"] for r in clean["ranking"]}
    b = {r["market_id"]: r["mean3_price"] for r in cad["ranking"]}
    assert all(abs(a[k] - b[k]) / a[k] < 0.005 for k in a)


def test_cost_gap_marks_feed_incomplete_and_never_estimates():
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-COST-GAP"])
    c = Extras(DEFAULT, ov).cost_pressure("Southeast", ["feed", "labor", "ice"], AS_OF)
    assert c["incomplete"] == ["feed_finfish_usd_per_ton"] and "feed_finfish_usd_per_ton" not in c["per_type"]
    assert "cost_data_incomplete" in c["flags"]


def test_oz_retail_converted_within_half_percent():
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-RETAIL-OZ"])
    from tests.helpers import gate_series
    fixed, _ = gate_series("Sturgeon caviar", "Pacific Northwest", ov, only={"SRC-RTL-01"})
    clean, _ = gate_series("Sturgeon caviar", "Pacific Northwest", only={"SRC-RTL-01"})
    assert fixed.sources["SRC-RTL-01"].flags["unit_mismatch"] == 6
    m = fixed.clean.merge(clean.clean, on="date", suffixes=("_f", "_c"))
    assert ((m.price_f / m.price_c - 1).abs() < 0.005).all()


def test_retail_is_not_cross_checked_so_clean_markets_have_no_disagreement():
    from tests.helpers import gate_series
    g, _ = gate_series("American lobster", "Northeast")
    assert "source_disagreement" not in g.flag_set() and "SRC-RTL-01" in g.usable_ids


def test_channel_fallback_when_series_missing(cfg):
    p = {"operation_type": "fishmonger_retailer", "region": "Northeast", "species": ["American lobster"],
         "customer_segment": "premium", "volume_lb_per_month": 6000, "question_type": "buy_now_or_wait"}
    res = run(p, llm=fake_llm(cfg), cfg=cfg, save=False)       # wholesale exists: no fallback
    assert "channel_fallback" not in res["flags"] and res["report"]["species"][0]["channel"] == "wholesale"


def test_operation_rules_are_read_from_data(catalog):
    with pytest.raises(ProfileError) as e:
        build_brief({"operation_type": "restaurant_buyer", "region": "Gulf", "species": ["Gulf shrimp"],
                     "customer_segment": "premium", "volume_lb_per_month": 100, "question_type": "best_months"}, catalog)
    assert "can ask" in str(e.value)
    # a species that does not fit the operation is accepted (it gets a caveat in the report, see test_any_species.py)
    b = build_brief({"operation_type": "finfish_farm", "region": "Gulf", "species": ["Gulf shrimp"],
                     "customer_segment": "premium", "volume_lb_per_month": 100}, catalog)
    assert b.species == "Gulf shrimp"


def test_multi_species_gives_one_answer_per_species_and_three_calls(cfg):
    p = {"operation_type": "inshore_boat", "region": "Mid-Atlantic", "species": ["Striped bass", "Summer flounder"],
         "customer_segment": "mainstream", "volume_lb_per_month": 15000}
    res = run(p, llm=fake_llm(cfg), cfg=cfg, save=False)
    assert res["analysis"]["direction"] == "per_species" and len(res["decision"]["by_series"]) == 2
    assert res["calls"] == 3


def test_quality_never_changes_trust_or_direction(cfg):
    p = {"operation_type": "wild_catch", "region": "Northeast", "species": ["Cod"], "customer_segment": "mainstream",
         "volume_lb_per_month": 40000}
    base = run(p, llm=fake_llm(cfg), cfg=cfg, save=False)
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-QUAL-UNVERIFIED"])
    bad = run(p, ov, llm=fake_llm(cfg, ov), cfg=cfg, save=False)
    assert bad["trust"] == base["trust"] and bad["analysis"]["direction"] == base["analysis"]["direction"]
    assert "quality_unverified" in bad["flags"]
    assert not re.search(r"quality (is|was) (confirmed|verified)", bad["report"]["summary_md"], re.I)


def test_no_api_key_pattern_in_repo():
    bad = []
    for p in ROOT.rglob("*"):
        if p.is_file() and ".git" not in p.parts and p.name not in {".env", "test_llm.py"} and p.suffix in {".py", ".md", ".json", ".toml", ".txt", ".jsonl", ".csv", ".yml"}:
            if re.search(r"sk-ant-[A-Za-z0-9_-]{20,}", p.read_text(errors="ignore")):
                bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad


def test_nothing_hard_codes_regions_or_operations():
    src = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))
    for word in ("Pacific Northwest", "pot_trap_fisher", "Hawaii-Pacific"):
        assert word not in src, word
