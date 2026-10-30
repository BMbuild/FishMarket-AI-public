"""Cleansing gate for the OECD aquaculture file, in the same spirit as the NOAA gate (cleansing.py).

Every row gets a status:
  VALID               usable as is
  REVIEW              usable, but carries flags the answer must mention
  EXCLUDED_BY_DESIGN  no observation (empty value): nothing to use, not an error
  REJECTED            impossible or malformed (negative value, bad year, unknown unit, duplicate key)
Flags (REVIEW): IMPUTED (OECD marks it imputed), CARRIED_FORWARD (identical to the previous year), JUMP_10X (more than 10x
or under 1/10 of the previous year, from a base of at least 100), PRICE_OUTLIER (value per kg outside $0.05-$100),
AGGREGATE (a "nei" species group, not a single species; informational).

    python -m fishmarket.oecd_clean          # reads data_real/oecd/aquaculture_production.csv, writes aquaculture_clean.csv + report"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import live

CLEAN = live.LOCAL_OECD.with_name("aquaculture_clean.csv")
REPORT = live.LOCAL_OECD.with_name("aquaculture_clean_report.json")
KEY = ["REF_AREA", "SPECIES", "UNIT_MEASURE", "TIME_PERIOD"]
UNITS = {"T", "USD"}
PRICE_MIN, PRICE_MAX = 0.05, 100.0          # US dollars per kg live weight
JUMP, JUMP_BASE = 10.0, 100.0
KEEP = ["REF_AREA", "Reference area", "MEASURE", "Measure", "SPECIES", "Species", "UNIT_MEASURE", "Unit of measure",
        "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "UNIT_MULT"]


def classify(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["v"] = pd.to_numeric(df["OBS_VALUE"].replace("", np.nan), errors="coerce")
    status = pd.Series("VALID", index=df.index)
    reason = pd.Series("", index=df.index)
    flags = pd.Series([[] for _ in range(len(df))], index=df.index)

    def reject(mask, why):
        m = mask & (status == "VALID")
        status[m], reason[m] = "REJECTED", why

    empty = df["OBS_VALUE"].astype(str).str.strip().eq("")
    status[empty], reason[empty] = "EXCLUDED_BY_DESIGN", "NO_OBSERVATION"
    reject(df["v"].isna() & ~empty, "NOT_A_NUMBER")
    reject(df["v"] < 0, "NEGATIVE")
    reject(~df["TIME_PERIOD"].astype(str).str.fullmatch(r"\d{4}"), "BAD_YEAR")
    reject(~df["UNIT_MEASURE"].isin(UNITS), "UNKNOWN_UNIT")
    reject(~df["UNIT_MULT"].astype(str).str.fullmatch(r"-?\d+") & df["UNIT_MULT"].astype(str).ne(""), "BAD_MULTIPLIER")
    dup = df.duplicated(KEY, keep=False) & (status == "VALID")
    reject(dup, "DUPLICATE_KEY")

    ok = status == "VALID"
    mult = pd.to_numeric(df["UNIT_MULT"], errors="coerce").fillna(0)
    df["value"] = df["v"] * 10.0 ** mult

    def flag(mask, name):
        for i in df.index[mask & ok]:
            flags[i] = flags[i] + [name]

    flag(df["OBS_STATUS"].eq("I"), "IMPUTED")
    flag(df["Species"].astype(str).str.contains(r"\bnei\b", case=False), "AGGREGATE")
    s = df[ok].sort_values(["REF_AREA", "SPECIES", "UNIT_MEASURE", "TIME_PERIOD"])
    prev = s.groupby(["REF_AREA", "SPECIES", "UNIT_MEASURE"])["value"].shift()
    py = s.groupby(["REF_AREA", "SPECIES", "UNIT_MEASURE"])["TIME_PERIOD"].shift().astype(float)
    consecutive = (s["TIME_PERIOD"].astype(float) - py) == 1
    flag(pd.Series(False, index=df.index) | ((s["value"] == prev) & (s["value"] > 0) & consecutive).reindex(df.index, fill_value=False), "CARRIED_FORWARD")
    ratio = s["value"] / prev
    jump = consecutive & (prev >= JUMP_BASE) & (s["value"] > 0) & ((ratio > JUMP) | (ratio < 1 / JUMP))
    flag(jump.reindex(df.index, fill_value=False), "JUMP_10X")
    w = df[ok].pivot_table(index=["REF_AREA", "SPECIES", "TIME_PERIOD"], columns="UNIT_MEASURE", values="value", aggfunc="first")
    if {"T", "USD"} <= set(w.columns):
        per_kg = w["USD"] / (w["T"] * 1000)
        bad = per_kg[(w["T"] > 0) & ((per_kg < PRICE_MIN) | (per_kg > PRICE_MAX))].index
        badset = set(bad)
        m = pd.Series([(a, b, c) in badset for a, b, c in zip(df["REF_AREA"], df["SPECIES"], df["TIME_PERIOD"])], index=df.index)
        flag(m, "PRICE_OUTLIER")
    review = ok & flags.map(lambda f: any(x != "AGGREGATE" for x in f))
    status[review] = "REVIEW"
    df["STATUS"], df["REASON"], df["FLAGS"] = status, reason, flags.map(lambda f: "|".join(f))
    return df


def report(c: pd.DataFrame) -> dict:
    counts = c["STATUS"].value_counts().to_dict()
    in_scope = len(c) - counts.get("EXCLUDED_BY_DESIGN", 0)
    usable = counts.get("VALID", 0) + counts.get("REVIEW", 0)
    fl = c.loc[c["FLAGS"] != "", "FLAGS"].str.split("|").explode().value_counts().to_dict()
    return {"rows": int(len(c)), "status": {k: int(v) for k, v in counts.items()},
            "rejected_reasons": {k: int(v) for k, v in c.loc[c["STATUS"] == "REJECTED", "REASON"].value_counts().items()},
            "flags": {k: int(v) for k, v in fl.items()}, "in_scope_pass_rate": round(usable / in_scope, 4) if in_scope else None}


def run(src: Path | None = None) -> dict:
    src = Path(src or live.LOCAL_OECD)
    raw = pd.read_csv(src, dtype=str, keep_default_na=False)
    c = classify(raw)
    keep = c[c["STATUS"].isin(["VALID", "REVIEW"])]
    cols = [k for k in KEEP if k in keep.columns] + ["STATUS", "FLAGS"]
    keep[cols].to_csv(CLEAN.with_name(CLEAN.name) if src == live.LOCAL_OECD else src.with_name("aquaculture_clean.csv"), index=False)
    rep = report(c)
    (REPORT if src == live.LOCAL_OECD else src.with_name("aquaculture_clean_report.json")).write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    r = run(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(r, indent=1))
