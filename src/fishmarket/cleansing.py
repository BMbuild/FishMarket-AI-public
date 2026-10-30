"""Validation gate between the Data Collection stage and the Analysis stage for NOAA FOSS landings.

Every row gets exactly one status and reason codes, so nothing is dropped silently:
  VALID               commercial row with usable pounds and dollars; may feed analysis
  REVIEW              usable numbers but suspicious (price far from the species' norm, missing source); kept OUT of confirmed analysis
  REJECTED            broken data (missing or negative values, withheld or unnamed species, impossible price, bad year, exact duplicate)
  EXCLUDED_BY_DESIGN  not an error: zero-fill placeholders (nothing landed) and recreational rows, which NOAA publishes without dollars
Recreational rows with pounds are routed to their own volume-only stream.
Why this exists: a first gate counted recreational rows (no dollars by design) as 'errors', which made 40% of the file look bad.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

FIRST_YEAR, LAST_YEAR = 1900, 2100
PRICE_FLOOR, PRICE_CEIL = 0.001, 5000.0        # USD/lb hard limits (elvers really sell for $2,000/lb, so the ceiling is high)
SPECIES_RATIO = 20.0                             # REVIEW when price is >20x or <1/20 of the species' median
MIN_ROWS_FOR_NORM = 8
COMMERCIAL, RECREATIONAL = "Commercial", "Recreational"
REQUIRED_COLUMNS = ["tsn", "ts_afs_name", "region_name", "state_name", "year", "pounds", "dollars", "source", "collection"]


class SchemaError(ValueError):
    pass


def _add(reasons: pd.Series, mask: pd.Series, code: str) -> None:
    reasons[mask] = reasons[mask] + code + ";"


def classify(raw: pd.DataFrame) -> pd.DataFrame:
    """Returns raw columns plus `stream`, `status`, `reasons`, `price` (USD/lb for priced rows)."""
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise SchemaError(f"CSV is missing required columns: {missing}")
    d = raw.copy()
    for c in ("pounds", "dollars", "year"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    name = d["ts_afs_name"].astype("string").str.strip()
    d["tsn"] = d["tsn"].astype("string")
    reasons = pd.Series("", index=d.index, dtype="object")
    status = pd.Series("VALID", index=d.index, dtype="object")
    stream = pd.Series("commercial_priced", index=d.index, dtype="object")
    com, rec = d["collection"] == COMMERCIAL, d["collection"] == RECREATIONAL
    other = ~(com | rec)
    _add(reasons, other, "unknown_collection")
    status[other], stream[other] = "REJECTED", "unknown"

    # ---- recreational: pounds only, by design no dollars
    stream[rec] = "recreational_volume"
    rec_ok = rec & (d["pounds"] > 0)
    status[rec] = "EXCLUDED_BY_DESIGN"
    _add(reasons, rec, "recreational_no_price")
    status[rec_ok] = "VALID"
    reasons[rec_ok] = ""
    rec_none = rec & ~rec_ok & (d["pounds"].isna() | (d["pounds"] == 0))     # survey gave fish counts but no weight
    reasons[rec_none] = "recreational_no_weight_estimate"
    rec_bad = rec & (d["pounds"] < 0)
    status[rec_bad] = "REJECTED"
    reasons[rec_bad] = "negative_pounds"

    # ---- commercial
    p, v = d["pounds"], d["dollars"]
    zero_fill = com & (p.isna() | (p == 0)) & (v.isna() | (v == 0))
    status[zero_fill], stream[zero_fill] = "EXCLUDED_BY_DESIGN", "zero_fill"
    _add(reasons, zero_fill, "zero_fill_no_landings")
    live = com & ~zero_fill
    withheld = live & (name.isna() | name.str.upper().str.contains("WITHHELD", na=False) | (d["tsn"].astype(str) == "0"))
    _add(reasons, withheld, "withheld_or_unnamed_species")
    _add(reasons, live & d["region_name"].isna(), "missing_region")
    _add(reasons, live & p.isna(), "missing_pounds")
    _add(reasons, live & v.isna(), "missing_dollars")
    _add(reasons, live & (p < 0), "negative_pounds")
    _add(reasons, live & (v < 0), "negative_dollars")
    _add(reasons, live & (p == 0) & (v > 0), "zero_pounds_with_dollars")
    _add(reasons, live & (v == 0) & (p > 0), "zero_dollars_with_pounds")
    yr_bad = live & (d["year"].isna() | (d["year"] < FIRST_YEAR) | (d["year"] > LAST_YEAR) | (d["year"] % 1 != 0))
    _add(reasons, yr_bad, "bad_year")
    priced = live & (p > 0) & (v > 0)
    d["price"] = np.where(priced, v / p.where(p > 0), np.nan)
    _add(reasons, priced & ((d["price"] < PRICE_FLOOR) | (d["price"] > PRICE_CEIL)), "price_out_of_bounds")
    hard = live & (reasons != "")
    status[hard] = "REJECTED"
    # exact duplicates among rows still standing (same key AND same numbers): keep the first
    ok = live & ~hard
    dup = ok & d.duplicated(["tsn", "state_name", "year", "source", "pounds", "dollars"], keep="first")
    _add(reasons, dup, "exact_duplicate")
    status[dup] = "REJECTED"
    ok = ok & ~dup
    # review rules (do not break the row, but keep it out of confirmed analysis)
    _add(reasons, ok & d["source"].isna(), "missing_source")
    med = d[ok].groupby(name[ok])["price"].agg(["median", "size"])
    med = med[med["size"] >= MIN_ROWS_FOR_NORM]["median"]
    norm = name.map(med).astype(float)
    far = ok & norm.notna() & ((d["price"] > norm * SPECIES_RATIO) | (d["price"] < norm / SPECIES_RATIO))
    _add(reasons, far, "price_far_from_species_norm")
    review = ok & (reasons != "")
    status[review] = "REVIEW"
    d["stream"], d["status"], d["reasons"] = stream, status, reasons.str.rstrip(";")
    return d


def report(c: pd.DataFrame) -> dict:
    """Plain counts. `pass_rate_in_scope` excludes rows that are not errors by design, so it is the honest rate."""
    tot = len(c)
    by_status = c["status"].value_counts().to_dict()
    in_scope = tot - by_status.get("EXCLUDED_BY_DESIGN", 0)
    reasons = c["reasons"][c["reasons"] != ""].str.split(";").explode().value_counts().to_dict()
    com = c[c["collection"] == COMMERCIAL]
    com_scope = com[com["status"] != "EXCLUDED_BY_DESIGN"]
    return {"total_rows": tot, "by_status": {k: int(v) for k, v in by_status.items()},
            "valid_rows": int(by_status.get("VALID", 0)),
            "pass_rate_all_rows": round(by_status.get("VALID", 0) / tot, 4),
            "pass_rate_in_scope": round(by_status.get("VALID", 0) / max(in_scope, 1), 4),
            "commercial_pass_rate_in_scope": round(float((com_scope["status"] == "VALID").mean()), 4) if len(com_scope) else None,
            "reason_counts": {k: int(v) for k, v in reasons.items()},
            "by_collection": {k: {s: int(n) for s, n in g["status"].value_counts().items()} for k, g in c.groupby("collection")}}


def split(c: pd.DataFrame) -> dict:
    return {"valid_commercial": c[(c["status"] == "VALID") & (c["stream"] == "commercial_priced")],
            "valid_recreational": c[(c["status"] == "VALID") & (c["stream"] == "recreational_volume")],
            "review": c[c["status"] == "REVIEW"], "rejected": c[c["status"] == "REJECTED"],
            "excluded": c[c["status"] == "EXCLUDED_BY_DESIGN"]}


def write_outputs(c: pd.DataFrame, out_dir: Path) -> dict:
    """Review and rejected rows go to csv (small, inspectable). Valid rows are regenerated on demand, so they are not written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = split(c)
    parts["review"].to_csv(out_dir / "noaa_review.csv", index=False)
    parts["rejected"].to_csv(out_dir / "noaa_rejected.csv", index=False)
    rep = report(c)
    (out_dir / "validation_report.json").write_text(json.dumps(rep, indent=2))
    return rep
