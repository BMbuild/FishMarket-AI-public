"""Lot 2 of the reliability audit: source reliability and data quality. A source the gate could not
compare, could not read, or could not date must lower confidence and say so, never pass silently."""
import pandas as pd
import pytest

from fishmarket import gate as G, loader
from fishmarket.config import DEFAULT
from fishmarket.registry import load_catalog, load_registry
from fishmarket.templates import CAVEATS, caveats_for
from fishmarket.trust import compute_trust
from helpers import AS_OF

SP, RG = "Gulf shrimp", "Gulf"


@pytest.fixture(scope="module")
def base():
    reg = load_registry(DEFAULT)
    raws = loader.load_all(DEFAULT, reg, None)
    ids = [s for s in raws if reg.loc[s, "trust_tier"] != "D" and reg.loc[s, "price_basis"] != "retail"
           and loader.covers_series(raws[s], SP, RG)]
    assert len(ids) >= 3, ids
    return reg, raws, ids, load_catalog(DEFAULT)


def gate(base, raws=None, reg=None):
    r0, raws0, ids, cat = base
    return G.run_gate(DEFAULT, r0 if reg is None else reg, raws0 if raws is None else raws, ids, SP, RG, AS_OF, cat)


def trust_of(g):
    return compute_trust(set(g.series_flags), g.usable_tiers())


def series_rows(df):
    return (df["species"] == SP) & (df["region"] == RG)


def test_baseline_is_clean_and_high(base):
    g = gate(base)
    assert g.series_flags == {} and trust_of(g)["rating"] == "high"


# ---- 4. sources that were never compared ------------------------------------------------------------

def test_sources_sharing_too_few_months_are_flagged_not_cross_checked(base):
    reg, raws, ids, _ = base
    primary, other = ids[0], ids[1]
    r = dict(raws)
    d = raws[other]
    m = series_rows(d)
    # both sources stay fresh and long enough, but never report the same month
    p = raws[primary]
    pm = series_rows(p)
    pmonths = pd.to_datetime(p.loc[pm, "date"]).dt.month
    r[primary] = pd.concat([p[~pm], p[pm][pmonths % 2 == 1]])
    omonths = pd.to_datetime(d.loc[m, "date"]).dt.month
    r[other] = pd.concat([d[~m], d[m][omonths % 2 == 0]])
    g = gate(base, raws=r)
    assert g.series_flags.get("not_cross_checked") == 1
    assert other in [s for pair in g.not_compared for s in pair]
    t = trust_of(g)
    assert t["rating"] == "medium"
    assert "Some sources share too few recent months to be compared." in t["reasons"]


# ---- 5. a whole selected file that could not be read --------------------------------------------------

def test_whole_file_missing_a_column_is_flagged_source_rejected(base):
    reg, raws, ids, _ = base
    r = dict(raws)
    r[ids[0]] = raws[ids[0]].drop(columns=["price"])
    g = gate(base, raws=r)
    assert ids[0] not in g.usable_ids
    assert g.series_flags.get("source_rejected") == 1
    assert trust_of(g)["rating"] == "medium"


def test_file_with_no_usable_rows_is_flagged_source_rejected(base):
    reg, raws, ids, _ = base
    r = dict(raws)
    d = raws[ids[1]].copy()
    d.loc[series_rows(d), "price"] = "-1"
    r[ids[1]] = d
    g = gate(base, raws=r)
    assert g.series_flags.get("source_rejected") == 1 and trust_of(g)["rating"] == "medium"


def test_stale_source_is_not_also_counted_as_rejected(base):
    reg, raws, ids, _ = base
    reg2 = reg.copy()
    reg2.loc[ids[1], "last_updated"] = "2025-01-01"
    g = gate(base, reg=reg2)
    assert "stale_data" in g.series_flags and "source_rejected" not in g.series_flags


# ---- 6. rows that claim to come from another source ---------------------------------------------------

def test_rows_naming_another_source_are_dropped_as_schema(base):
    reg, raws, ids, _ = base
    r = dict(raws)
    d = raws[ids[0]].copy()
    idx = d[series_rows(d)].index[:4]
    d.loc[idx, "source_id"] = "SRC-SOMEONE-ELSE"
    r[ids[0]] = d
    g = gate(base, raws=r)
    rep = g.sources[ids[0]]
    assert rep.flags.get("schema") == 4 and rep.rows_kept == rep.rows_in - 4
    assert trust_of(g)["rating"] == "medium"


# ---- 7. a registry date in the future ---------------------------------------------------------------

def test_registry_date_after_as_of_rejects_the_source(base):
    reg, raws, ids, _ = base
    reg2 = reg.copy()
    reg2.loc[ids[0], "last_updated"] = "2027-03-01"
    g = gate(base, reg=reg2)
    rep = g.sources[ids[0]]
    assert not rep.usable and "after the as-of date" in rep.excluded_reason
    assert g.series_flags.get("source_rejected") == 1 and trust_of(g)["rating"] == "medium"


# ---- 8. duplicates ----------------------------------------------------------------------------------

def _with_duplicate(raws, sid, factor):
    d = raws[sid]
    row = d[series_rows(d)].tail(1).copy()
    row["price"] = str(float(row["price"].iloc[0]) * factor)
    return pd.concat([row, d]), pd.Timestamp(row["date"].iloc[0])


def test_conflicting_duplicates_are_all_dropped(base):
    reg, raws, ids, _ = base
    r = dict(raws)
    r[ids[0]], month = _with_duplicate(raws, ids[0], 1.4)
    g = gate(base, raws=r)
    rep = g.sources[ids[0]]
    assert rep.flags.get("duplicates") == 2
    assert month not in set(rep.clean["date"])
    assert any("disagree" in a for a in rep.actions)


def test_identical_duplicates_keep_one_copy(base):
    reg, raws, ids, _ = base
    r = dict(raws)
    r[ids[0]], month = _with_duplicate(raws, ids[0], 1.0)
    g = gate(base, raws=r)
    rep = g.sources[ids[0]]
    assert rep.flags.get("duplicates") == 1
    assert (rep.clean["date"] == month).sum() == 1


# ---- trust table and caveat sentences ----------------------------------------------------------------

@pytest.mark.parametrize("flags,tiers,rating", [
    ({"not_cross_checked"}, ["A", "B"], "medium"),
    ({"source_rejected"}, ["A", "B"], "medium"),
    ({"source_rejected", "source_disagreement"}, ["A", "C"], "low"),    # low still wins
    ({"not_cross_checked"}, ["C"], "low"),
])
def test_trust_for_new_flags(flags, tiers, rating):
    out = compute_trust(flags, tiers)
    assert out["rating"] == rating
    assert not any(ch.isdigit() for r in out["reasons"] for ch in r)


def test_new_caveat_sentences_are_fixed():
    assert CAVEATS["not_cross_checked"] == ("Two sources share too few recent months to be compared, "
                                            "so the figures could not be fully cross-checked.")
    assert CAVEATS["source_rejected"] == ("A selected source was left out because its file could not be "
                                          "read correctly.")
    assert caveats_for({"not_cross_checked", "source_rejected"}) == [CAVEATS["source_rejected"],
                                                                     CAVEATS["not_cross_checked"]]
