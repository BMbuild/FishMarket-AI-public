import pytest

from fishmarket.analytics import compute_stats
from fishmarket.grounding import check_analysis, numerals_in, round_half_up
from fishmarket.schemas import Claim, NumberRef, StatRow
from fishmarket.templates import template_analysis
from helpers import AS_OF, gate_series


def stats_for(species, region):
    g, _ = gate_series(species, region)
    return compute_stats(g.clean, f"{species}|{region}", g.primary_id, AS_OF)["stats"]


@pytest.fixture(scope="module")
def shrimp():
    return stats_for("Gulf shrimp", "Gulf")


def good(stats):
    return template_analysis(stats, None, with_lens=False)


def test_accepts_a_correct_analysis(shrimp):
    assert check_analysis(good(shrimp), shrimp) == []


def test_rejects_fabricated_number(shrimp):
    a = good(shrimp)
    a.claims[0].text += " Prices could rise 99.9% soon."
    assert any(v.startswith("G2") and "99.9" in v for v in check_analysis(a, shrimp))


def test_rejects_declared_number_that_does_not_match_statistic(shrimp):
    a = good(shrimp)
    a.claims[0].numbers[0].value = 1.55
    a.claims[0].text = a.claims[0].text.replace("1.20", "1.55")
    assert any(v.startswith("G2") for v in check_analysis(a, shrimp))


def test_rejects_unknown_stat_id(shrimp):
    a = good(shrimp)
    a.claims[1].stat_ids = ["S99"]
    assert any(v.startswith("G1") and "S99" in v for v in check_analysis(a, shrimp))


def test_rejects_claim_with_no_stat_id(shrimp):
    a = good(shrimp)
    a.claims[0].stat_ids = []
    assert any(v.startswith("G1") for v in check_analysis(a, shrimp))


def test_rejects_wrong_direction(shrimp):
    a = good(shrimp)
    a.direction = "sell_now"
    assert any(v.startswith("G3") for v in check_analysis(a, shrimp))


def test_driver_tags_are_derived_by_python_not_checked_against_the_model(shrimp):
    from fishmarket.grounding import expected_tags
    a = good(shrimp)
    a.driver_tags = ["rising_trend"]                      # the model no longer controls tags: ignored by the check
    assert not any(v.startswith("G4") for v in check_analysis(a, shrimp))
    assert "seasonal_peak_ahead" in expected_tags(shrimp, "hold")


def test_model_tool_schema_has_no_driver_tags():
    from fishmarket.agents.agent2 import ANALYSIS_TOOL
    assert "driver_tags" not in ANALYSIS_TOOL["input_schema"]["properties"]
    assert "driver_tags" not in ANALYSIS_TOOL["input_schema"].get("required", [])


def test_rejects_unknown_claim_reference_in_action(shrimp):
    a = good(shrimp)
    a.actions[0].claim_ids = ["C42"]
    assert any(v.startswith("G5") for v in check_analysis(a, shrimp))


def test_rejects_peak_month_on_a_weak_series():
    st = stats_for("Tilapia", "Southeast")
    peak = next(s for s in st if s.kind == "seasonal_peak_month")
    assert peak.reliability == "weak"
    a = good(st)
    a.claims.append(Claim(id="C9", text=f"Prices peak in {peak.month}.", stat_ids=[peak.id]))
    assert any(v.startswith("G6") for v in check_analysis(a, st))
    b = good(st)
    b.claims.append(Claim(id="C9", text=f"Prices usually peak in {peak.month}.", stat_ids=[st[0].id]))
    assert any(v.startswith("G6") for v in check_analysis(b, st))


def test_peak_month_on_a_strong_series_is_allowed(shrimp):
    peak = next(s for s in shrimp if s.kind == "seasonal_peak_month")
    a = good(shrimp)
    a.claims = [c for c in a.claims if peak.id not in c.stat_ids] + [
        Claim(id="C9", text=f"Prices usually peak in {peak.month}.", stat_ids=[peak.id])]
    assert check_analysis(a, shrimp) == []


def test_rounding_is_half_up_not_bankers():
    assert str(round_half_up(2.675, 2)) == "2.68"      # float 2.675 is 2.67499..., repr gives 2.675
    assert str(round_half_up(0.125, 2)) == "0.13"
    assert str(round_half_up(-2.83, 1)) == "2.8"       # magnitude


def test_half_up_declaration_is_accepted():
    st = [StatRow(id="S1", series="x", kind="best_next3_vs_now_ratio", value=1.125, unit="ratio"),
          StatRow(id="S2", series="x", kind="latest_price", value=2.675, unit="usd_per_lb"),
          StatRow(id="S3", series="x", kind="yoy_price_change_pct", value=-2.83, unit="percent")]
    a = template_analysis(st, None)
    a.claims = [Claim(id="C1", text="Ratio is 1.13.", stat_ids=["S1"], numbers=[NumberRef(value=1.13, stat_id="S1")]),
                Claim(id="C2", text="Price is $2.68.", stat_ids=["S2"], numbers=[NumberRef(value=2.68, stat_id="S2")]),
                Claim(id="C3", text="Prices fell 2.8%.", stat_ids=["S3"], numbers=[NumberRef(value=-2.8, stat_id="S3")])]
    assert check_analysis(a, st) == []


def test_numeral_exemptions():
    assert numerals_in("In 2026 over the next 3 months and the last 12-month stretch, up 4.5% to $1,204.50") == \
        [__import__("decimal").Decimal("4.5"), __import__("decimal").Decimal("1204.50")]
    assert numerals_in("see S3 and Q4") == []
