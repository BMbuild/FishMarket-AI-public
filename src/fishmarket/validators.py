"""Validation gates for every external source, returning a StageHandoff (OK / WARNING / FLAGGED).
A FLAGGED result always carries flag_reason and required_action, and may not feed a confirmed analysis (contracts.ensure_confirmable)."""
from __future__ import annotations

import pandas as pd

from .contracts import StageHandoff


def _h(status: str, payload: dict, reason: str | None = None, action: str | None = None) -> StageHandoff:
    return StageHandoff(stage="collection", status=status, payload=payload, flag_reason=reason, required_action=action)


# ---------------------------------------------------------------- NOAA landings series
def gate_series(loaded, species_clean: str, region: str | None = None) -> StageHandoff:
    """Gate for one species/region selected in the app, using the full row-level classification."""
    from . import handoff as ho, real_data
    c = loaded.classified
    raw_name = loaded.df.loc[loaded.df["species"] == species_clean, "ts_afs_name"]
    s = real_data.series(loaded.df, species_clean, region)
    if s.empty or raw_name.empty:
        return _h("FLAGGED", {"valid_years": 0}, "No valid annual rows for this species and region.",
                  "Choose another species or region, or inspect noaa_rejected.csv for this species.")
    sel = c[c["ts_afs_name"].isin(set(raw_name))]
    if region and region != "All regions":
        sel = sel[sel["region_name"] == region]
    counts = sel["status"].value_counts().to_dict()
    h = ho.from_series(s, species_clean, region or "All regions")
    gap = ho.gap_report(h)
    payload = {"valid_years": gap["count"], "gaps": gap["missing"], "row_status": {k: int(v) for k, v in counts.items()}}
    problems = []
    if counts.get("REVIEW"):
        problems.append(f"{counts['REVIEW']} row(s) held back for review (price far from this species' norm)")
    if counts.get("REJECTED"):
        problems.append(f"{counts['REJECTED']} row(s) rejected (missing, zero or negative values)")
    if gap["missing"]:
        problems.append(f"missing years: {gap['missing'][:6]}")
    if gap["count"] < 3:
        return _h("FLAGGED", payload, "Fewer than 3 valid years.", "Treat any figure as a single data point, not a trend.")
    if problems:
        return _h("WARNING", payload, "; ".join(problems),
                  "Excluded rows are not in the calculation; see noaa_rejected.csv and noaa_review.csv.")
    return _h("OK", payload)


# ---------------------------------------------------------------- GBIF
def validate_gbif_match(m: dict, min_confidence: int = 90) -> StageHandoff:
    if not isinstance(m, dict) or not m.get("usageKey"):
        return _h("FLAGGED", {}, "GBIF returned no usable taxon key.", "Check the scientific name spelling; do not use GBIF facts for this species.")
    if m.get("matchType") in (None, "NONE", "HIGHERRANK") or m.get("confidence", 0) < min_confidence:
        return _h("FLAGGED", {"matchType": m.get("matchType"), "confidence": m.get("confidence")},
                  "GBIF match is not exact or confident enough.", "Use a full genus and species name.")
    if m.get("status") not in (None, "ACCEPTED"):
        return _h("WARNING", {"status": m.get("status")}, f"GBIF taxon status is {m.get('status')}.", "Prefer the accepted name.")
    return _h("OK", {"key": m["usageKey"]})


def clean_points(rows: list[dict]) -> tuple[list[tuple[float, float]], dict]:
    """Keep only plausible coordinates; report what was dropped."""
    pts, bad, dup = [], 0, 0
    seen = set()
    for r in rows:
        la, lo = r.get("decimalLatitude"), r.get("decimalLongitude")
        if not isinstance(la, (int, float)) or not isinstance(lo, (int, float)) or not (-90 <= la <= 90 and -180 <= lo <= 180) or (la == 0 and lo == 0):
            bad += 1
            continue
        k = (round(la, 4), round(lo, 4))
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        pts.append((la, lo))
    return pts, {"kept": len(pts), "invalid_dropped": bad, "duplicate_dropped": dup}


# ---------------------------------------------------------------- FishBase
def validate_fishbase(resp: dict) -> StageHandoff:
    if not isinstance(resp, dict) or not {"count", "returned", "data", "error"} <= set(resp):
        return _h("FLAGGED", {}, "FishBase response does not have the documented shape (count, returned, data, error).",
                  "Check the API base URL; do not use FishBase facts.")
    if resp["error"]:
        return _h("FLAGGED", {}, f"FishBase reported an error: {str(resp['error'])[:100]}", "Retry later or check the query.")
    if not resp["data"]:
        return _h("WARNING", {"count": 0}, "FishBase has no record for this name.", "Shellfish and invertebrates may be in SeaLifeBase instead.")
    return _h("OK", {"count": resp["count"]})


# ---------------------------------------------------------------- NOAA foreign trade
def validate_trade(df: pd.DataFrame) -> StageHandoff:
    """Generic gate: the trade endpoint's field names are not verified, so columns are found by name."""
    if df is None or df.empty:
        return _h("FLAGGED", {"rows": 0}, "No trade rows.", "Run scripts/fetch_noaa_trade.py from a machine that can reach NOAA.")
    cols = {c.lower(): c for c in df.columns}
    qty = next((cols[c] for c in cols if any(k in c for k in ("kg", "kilogram", "pound", "quantity", "volume"))), None)
    val = next((cols[c] for c in cols if any(k in c for k in ("value", "dollar", "usd"))), None)
    yr = next((cols[c] for c in cols if c in ("year", "period") or "year" in c), None)
    if not (qty and val and yr):
        return _h("FLAGGED", {"columns": list(df.columns)[:15]}, "Cannot find quantity, value and year columns.",
                  "Inspect the response and map the columns before analysis.")
    q, v, y = (pd.to_numeric(df[c], errors="coerce") for c in (qty, val, yr))
    bad = int((q.isna() | v.isna() | y.isna() | (q <= 0) | (v < 0)).sum())
    payload = {"rows": int(len(df)), "bad_rows": bad, "columns_used": [qty, val, yr]}
    if bad / len(df) > 0.5:
        return _h("FLAGGED", payload, f"{bad} of {len(df)} trade rows have missing or non-positive values.", "Fix the extraction before use.")
    if bad:
        return _h("WARNING", payload, f"{bad} trade row(s) have missing or non-positive values and will be excluded.", "Exclude them from price calculations.")
    return _h("OK", payload)
