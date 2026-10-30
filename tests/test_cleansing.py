import pandas as pd
import pytest

from fishmarket import cleansing as C
from fishmarket import validators as V


def row(**kw):
    base = dict(tsn="1", ts_afs_name="COD, ATLANTIC", ts_scientific_name="Gadus morhua", region_name="New England", state_name="MAINE",
                year=2020, pounds=1000.0, dollars=2000.0, tot_count=None, source="ACCSP", collection="Commercial")
    base.update(kw)
    return base


def run(rows):
    return C.classify(pd.DataFrame(rows))


def one(**kw):
    r = run([row(**kw)]).iloc[0]
    return r["status"], r["reasons"]


def test_good_row_is_valid_with_price():
    c = run([row()])
    assert c.iloc[0]["status"] == "VALID" and c.iloc[0]["price"] == 2.0


@pytest.mark.parametrize("kw,status,reason", [
    (dict(dollars=None), "REJECTED", "missing_dollars"),
    (dict(pounds=None), "REJECTED", "missing_pounds"),
    (dict(pounds=-5.0), "REJECTED", "negative_pounds"),
    (dict(dollars=-5.0), "REJECTED", "negative_dollars"),
    (dict(dollars=0.0), "REJECTED", "zero_dollars_with_pounds"),
    (dict(pounds=0.0), "REJECTED", "zero_pounds_with_dollars"),
    (dict(pounds=None, dollars=None), "EXCLUDED_BY_DESIGN", "zero_fill_no_landings"),
    (dict(pounds=0.0, dollars=0.0), "EXCLUDED_BY_DESIGN", "zero_fill_no_landings"),
    (dict(ts_afs_name="WITHHELD FOR CONFIDENTIALITY", tsn="0"), "REJECTED", "withheld_or_unnamed_species"),
    (dict(region_name=None), "REJECTED", "missing_region"),
    (dict(year=None), "REJECTED", "bad_year"),
    (dict(dollars=1e9), "REJECTED", "price_out_of_bounds"),
    (dict(dollars=0.0001), "REJECTED", "price_out_of_bounds"),
    (dict(source=None), "REVIEW", "missing_source"),
])
def test_commercial_rules(kw, status, reason):
    s, r = one(**kw)
    assert s == status and reason in r


def test_recreational_without_dollars_is_not_an_error():
    s, r = one(collection="Recreational", dollars=None, pounds=500.0)
    assert (s, r) == ("VALID", "")
    s, r = one(collection="Recreational", dollars=None, pounds=None)
    assert s == "EXCLUDED_BY_DESIGN"
    assert one(collection="Recreational", dollars=None, pounds=-1.0)[0] == "REJECTED"


def test_exact_duplicate_second_copy_rejected_but_different_numbers_kept():
    c = run([row(), row(), row(pounds=900.0, dollars=1800.0)])
    assert list(c["status"]) == ["VALID", "REJECTED", "VALID"] and "exact_duplicate" in c.iloc[1]["reasons"]


def test_price_far_from_species_norm_goes_to_review_not_valid():
    rows = [row(year=1990 + i, dollars=2000.0 + i) for i in range(10)] + [row(year=2015, dollars=2000.0 * 50)]
    c = run(rows)
    assert c.iloc[-1]["status"] == "REVIEW" and (c.iloc[:-1]["status"] == "VALID").all()


def test_every_row_gets_exactly_one_status_and_report_adds_up():
    c = run([row(), row(dollars=None), row(collection="Recreational", dollars=None), row(pounds=None, dollars=None)])
    r = C.report(c)
    assert sum(r["by_status"].values()) == r["total_rows"] == 4
    assert r["pass_rate_in_scope"] > r["pass_rate_all_rows"]


def test_missing_columns_raise():
    with pytest.raises(C.SchemaError):
        C.classify(pd.DataFrame({"year": [1]}))


def test_write_outputs(tmp_path):
    rep = C.write_outputs(run([row(), row(dollars=None)]), tmp_path)
    assert (tmp_path / "noaa_rejected.csv").exists() and (tmp_path / "validation_report.json").exists() and rep["valid_rows"] == 1


# ---------- validators for the other sources
def test_gbif_match_gate():
    assert V.validate_gbif_match({"usageKey": 1, "matchType": "EXACT", "confidence": 99, "status": "ACCEPTED"}).status == "OK"
    h = V.validate_gbif_match({"usageKey": 1, "matchType": "HIGHERRANK", "confidence": 50})
    assert h.status == "FLAGGED" and h.flag_reason and h.required_action
    assert V.validate_gbif_match({}).status == "FLAGGED"
    assert V.validate_gbif_match({"usageKey": 1, "matchType": "EXACT", "confidence": 99, "status": "SYNONYM"}).status == "WARNING"


def test_clean_points():
    pts, st = V.clean_points([{"decimalLatitude": 43.0, "decimalLongitude": -70.0}, {"decimalLatitude": 43.0, "decimalLongitude": -70.0},
                              {"decimalLatitude": 99.0, "decimalLongitude": 0.0}, {"decimalLatitude": 0, "decimalLongitude": 0}, {}])
    assert pts == [(43.0, -70.0)] and st == {"kept": 1, "invalid_dropped": 3, "duplicate_dropped": 1}


def test_fishbase_gate():
    ok = {"count": 1, "returned": 1, "data": [{"a": 1}], "error": None}
    assert V.validate_fishbase(ok).status == "OK"
    assert V.validate_fishbase({**ok, "data": [], "count": 0}).status == "WARNING"
    assert V.validate_fishbase({**ok, "error": "boom"}).status == "FLAGGED"
    assert V.validate_fishbase({"html": "<p>"}).status == "FLAGGED"


def test_trade_gate():
    good = pd.DataFrame({"year": [2022, 2023], "kilograms": [10, 20], "value": [100, 250]})
    assert V.validate_trade(good).status == "OK"
    assert V.validate_trade(good.assign(value=[100, None])).status == "WARNING"
    assert V.validate_trade(pd.DataFrame({"x": [1]})).status == "FLAGGED"
    assert V.validate_trade(pd.DataFrame()).status == "FLAGGED"


def test_series_gate_on_real_file():
    from fishmarket import contracts, real_data
    if not real_data.DEFAULT_CSV.exists():
        pytest.skip("no csv")
    L = real_data.load()
    h = V.gate_series(L, "American lobster")
    assert h.status in {"OK", "WARNING"} and h.payload["valid_years"] > 50
    contracts.ensure_confirmable([h])
    assert V.gate_series(L, "No such fish").status == "FLAGGED"
