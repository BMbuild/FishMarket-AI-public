import pandas as pd
import pytest

from fishmarket import cleansing, contracts, real_data, tools
from fishmarket.sources import SOURCES

CSV = real_data.DEFAULT_CSV
pytestmark = pytest.mark.skipif(not CSV.exists(), reason="NOAA csv not present")


@pytest.fixture(scope="module")
def real():
    return real_data.load()


def test_clean_name():
    assert real_data.clean_name("COD, PACIFIC") == "Pacific cod"
    assert real_data.clean_name("MENHADENS **") == "Menhadens"


def test_cleaning_drops_recreational_and_withheld(real):
    assert real.notes["excluded_by_design_rows"] > 0
    assert not real.df["species"].str.contains("withheld", case=False).any()
    assert ((real.df.price >= cleansing.PRICE_FLOOR) & (real.df.price <= cleansing.PRICE_CEIL)).all()
    assert not real.df.duplicated(["species", "region", "year"]).any()


def test_lobster_analysis_is_plausible(real):
    a = real_data.analyse(real.df, "American lobster")
    assert a["ok"] and a["last_year"] >= 2023 and 3 < a["latest_price"] < 12
    assert a["trend_direction"] in {"up", "down", "flat"}
    assert any("Annual data" in c for c in a["caveats"])


def test_short_series_is_refused():
    df = pd.DataFrame({"species": ["x"] * 2, "region": ["r"] * 2, "year": [2023, 2024], "pounds": [1.0, 1.0], "dollars": [1.0, 2.0]})
    assert real_data.analyse(df, "x")["ok"] is False


def test_tools_output_validates(real):
    rows = tools.get_fish_prices("American lobster", real=real.df)
    assert tools.validate_market_data(rows)["ok"]
    assert not tools.validate_market_data([{"date": "", "price": -1, "unit": "lb", "source": "s"}])["ok"]
    assert tools.get_fish_prices("American lobster")[0]["source"].endswith("(fictional)")


def test_compare_regions(real):
    c = tools.compare_market_price(real.df, "American lobster", "New England", "Middle Atlantic") if False else \
        tools.compare_market_price("American lobster", "New England", "Middle Atlantic", real.df)
    assert c["ok"] and c["unit"] == "USD/lb"


def test_flagged_contract():
    with pytest.raises(ValueError):
        contracts.StageHandoff(stage="collection", status="FLAGGED", payload={})
    ok = contracts.StageHandoff(stage="collection", status="FLAGGED", payload={}, flag_reason="stale", required_action="refresh")
    with pytest.raises(contracts.FlaggedRecordError):
        contracts.ensure_confirmable([ok])
    contracts.ensure_confirmable([contracts.StageHandoff(stage="collection", status="OK", payload={})])


def test_sources_honest_about_placeholders():
    by = {s["id"]: s for s in SOURCES}
    assert by["NOAA-VESSELS"]["status"] == "needs_real_url" and by["NOAA-LANDINGS"]["status"] == "in_use"


def test_inflation_adjustment(real):
    t = real_data.real_trend(real.df, "American lobster")
    assert t["ok"] and t["real_cagr_pct"] < t["nominal_cagr_pct"]
    assert abs((t["nominal_cagr_pct"] - t["real_cagr_pct"]) - t["inflation_cagr_pct"]) < 0.6
    c = real_data.cpi()
    assert c[1950] == 24.1 and c[2024] == 313.689


def test_states_and_concentration(real):
    tb = real_data.state_table(real.states, "American lobster")
    assert abs(tb["share_pct"].sum() - 100) < 0.01 and tb.iloc[0]["state"] == "Maine"
    assert real_data.concentration(tb)["label"] == "highly concentrated"


def test_browse_and_movers(real):
    t = real_data.top_species(real.df)
    assert t["dollars"].is_monotonic_decreasing and len(t) == 15
    m = real_data.movers(real.df)
    assert (m["up"]["price_chg_pct"].diff().dropna() <= 0).all() and (m["down"]["dollars"] >= 5e6).all()


def test_rec_vs_commercial(real):
    r = real_data.rec_vs_commercial(real, "Summer flounder")
    assert r["ok"] and 0 < r["rec_share_pct"] < 100
    assert real_data.rec_vs_commercial(real, "No such fish")["ok"] is False


def test_interpretation_flags():
    assert real_data.interpretation_flags({"yoy_price_pct": 15, "yoy_pounds_pct": -20})[0].startswith("Price rose while landings fell")
    assert real_data.interpretation_flags({"yoy_price_pct": 1, "yoy_pounds_pct": 2}) == []


def test_real_summary_grounding(real):
    from fishmarket import real_summary as S
    from fishmarket.llm import FakeLLM
    a = real_data.analyse(real.df, "American lobster")
    cl = S.build_claims(a, real_data.real_trend(real.df, "American lobster"))

    def llm(text):
        m = FakeLLM({"summary": lambda s, u, t, n: {"markdown": text}})
        m.mode = "live"
        return m
    good = f"Lobster fetched ${a['latest_price']:.2f} per lb in {a['last_year']}, {a['yoy_price_pct']:+.1f}% on the year before."
    assert S.summarise(cl, llm(good))["source"] == "ai"
    bad = S.summarise(cl, llm("Lobster fetched $9.99 per lb."))
    assert bad["source"] == "template" and "not in the verified claims" in bad["reason"]
    assert "advice" in S.summarise(cl, llm("You should sell now."))["reason"]
    assert S.summarise(cl, None)["source"] == "template"


def test_real_series_passes_through_handoff_contract(real):
    from fishmarket import handoff
    h = handoff.from_series(real_data.series(real.df, "American lobster"), "American lobster", "All regions")
    g = handoff.gap_report(h)
    assert g["complete"] and g["last"] >= 2023
    # volume-weighted average computed by the analyst function equals dollars / pounds over the same years
    yrs = [int(o.period) for o in h.observations]
    out = handoff.agent_b(h.model_copy(update={"expected_periods": [str(y) for y in yrs]}))
    s = real_data.series(real.df, "American lobster")
    assert abs(float(out["volume_weighted_average"]) - s["dollars"].sum() / s["pounds"].sum()) < 1e-6
