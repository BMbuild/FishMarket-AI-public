"""Step 3: verification gate. Pure Python, free. Repairs what can be repaired, records every action,
never invents values."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .config import Config, DEFAULT
from .loader import REQUIRED_COLUMNS
from .registry import TIER_RANK


@dataclass
class SourceReport:
    source_id: str
    tier: str
    covers: bool = False
    flags: dict = field(default_factory=dict)
    rows_in: int = 0
    rows_kept: int = 0
    usable: bool = False
    excluded_reason: Optional[str] = None
    last_updated: str = ""
    clean: Optional[pd.DataFrame] = None
    actions: list = field(default_factory=list)

    @property
    def rows_dropped(self) -> int:
        return self.rows_in - self.rows_kept

    def summary(self) -> dict:
        return {"source_id": self.source_id, "tier": self.tier, "covers": self.covers, "usable": self.usable,
                "excluded_reason": self.excluded_reason, "flags": dict(self.flags), "rows_in": self.rows_in,
                "rows_kept": self.rows_kept, "rows_dropped": self.rows_dropped,
                "last_updated": self.last_updated, "actions": list(self.actions)}


@dataclass
class GateReport:
    series: str
    sources: dict
    primary_id: Optional[str] = None
    clean: Optional[pd.DataFrame] = None
    series_flags: dict = field(default_factory=dict)
    usable_ids: list = field(default_factory=list)
    disagreements: list = field(default_factory=list)
    not_compared: list = field(default_factory=list)    # [primary, other] pairs with too few shared months
    hard_failure: bool = False
    failure_reasons: list = field(default_factory=list)

    def flag_set(self) -> set:
        return set(self.series_flags)

    def usable_tiers(self) -> list:
        return [self.sources[s].tier for s in self.usable_ids]

    def summary(self) -> dict:
        return {"series": self.series, "primary_id": self.primary_id, "usable": self.usable_ids,
                "series_flags": dict(self.series_flags), "disagreements": list(self.disagreements),
                "not_compared": list(self.not_compared),
                "hard_failure": self.hard_failure, "failure_reasons": list(self.failure_reasons),
                "sources": {k: v.summary() for k, v in self.sources.items()}}


def _blank(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().eq("")


def gate_source(raw: pd.DataFrame, reg_row, species: str, region: str, cfg: Config,
                as_of: pd.Timestamp, catalog: pd.DataFrame) -> SourceReport:
    updated = pd.to_datetime(reg_row["last_updated"], errors="coerce")
    rep = SourceReport(source_id=reg_row["source_id"], tier=str(reg_row["trust_tier"]),
                       last_updated=str(updated.date()) if pd.notna(updated) else "unknown")
    flags = rep.flags

    # 1. Schema
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing_cols:
        rep.covers = True
        rep.rows_in = len(raw)
        flags["schema"] = len(raw)
        rep.excluded_reason = f"missing columns: {', '.join(missing_cols)}"
        rep.actions.append(f"Dropped the whole file: {rep.excluded_reason}.")
        return rep
    d = raw[(raw["species"] == species) & (raw["region"] == region)].copy()
    rep.rows_in = len(d)
    if d.empty:
        rep.excluded_reason = "source has no rows for this series"
        return rep
    rep.covers = True

    price_blank, vol_blank = _blank(d["price"]), _blank(d["volume"])
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["price"] = pd.to_numeric(d["price"], errors="coerce")
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce")
    expected_type = str(catalog.loc[species, "source_type"]) if species in catalog.index else None
    bad = d["date"].isna()
    bad |= d["price"].isna() & ~price_blank          # present but unparseable
    bad |= d["volume"].isna() & ~vol_blank
    bad |= (d["price"] <= 0) | (d["volume"] <= 0)
    bad |= ~d["unit"].isin(["lb", "kg", "oz"])
    bad |= d["source_id"] != rep.source_id           # rows that say they come from another source
    if expected_type is not None:
        bad |= d["source_type"] != expected_type
    if bad.any():
        flags["schema"] = int(bad.sum())
        rep.actions.append(f"Dropped {int(bad.sum())} rows that failed schema checks.")
        d = d[~bad]

    # 2. Unit
    kg = d["unit"] == "kg"
    if kg.any():
        d.loc[kg, "price"] = d.loc[kg, "price"] / cfg.KG_TO_LB
        d.loc[kg, "volume"] = d.loc[kg, "volume"] * cfg.KG_TO_LB
        d.loc[kg, "unit"] = "lb"
        flags["unit_mismatch"] = int(kg.sum())
        rep.actions.append(f"Converted {int(kg.sum())} rows from kg to lb.")
    oz = d["unit"] == "oz"
    if oz.any():
        d.loc[oz, "price"] = d.loc[oz, "price"] * cfg.OZ_PER_LB
        d.loc[oz, "volume"] = d.loc[oz, "volume"] / cfg.OZ_PER_LB
        d.loc[oz, "unit"] = "lb"
        flags["unit_mismatch"] = flags.get("unit_mismatch", 0) + int(oz.sum())
        rep.actions.append(f"Converted {int(oz.sum())} rows from ounces to pounds.")

    # 3. Duplicates. Identical copies: keep one. Copies that disagree on price: keep none (never pick one).
    key = ["species", "region", "date"]
    dup = d.duplicated(key, keep=False)
    if dup.any():
        prices = d[dup].groupby(key)["price"].agg(lambda s: s.dropna().nunique() > 1)
        conflict_keys = set(prices[prices].index)
        conflict = d[key].apply(tuple, axis=1).isin(conflict_keys) if conflict_keys else dup & False
        n_conflict = int(conflict.sum())
        if n_conflict:
            months = ", ".join(sorted({k[2].strftime("%Y-%m") for k in conflict_keys}))
            rep.actions.append(f"Dropped all {n_conflict} copies of {len(conflict_keys)} month(s) whose copies "
                               f"disagree on price: {months}.")
            d = d[~conflict]
        n = int(d.duplicated(key).sum())
        if n:
            d = d.drop_duplicates(key, keep="first")
            rep.actions.append(f"Dropped {n} duplicate rows.")
        flags["duplicates"] = n + n_conflict

    # 4. Date range
    fut = d["date"] > as_of
    if fut.any():
        flags["date_range"] = int(fut.sum())
        rep.actions.append(f"Dropped {int(fut.sum())} rows dated after the as-of date.")
        d = d[~fut]

    # 5. Missing values
    miss = d["price"].isna()
    if miss.any():
        flags["missing_values"] = int(miss.sum())
        rep.actions.append(f"Dropped {int(miss.sum())} rows with no price (not estimated).")
        d = d[~miss]
    if bool(reg_row["has_volume"]) and d["volume"].isna().any():
        nv = int(d["volume"].isna().sum())
        flags["missing_values"] = flags.get("missing_values", 0) + nv
        rep.actions.append(f"{nv} rows have a blank volume (kept, volume left blank).")

    d = d.sort_values("date").reset_index(drop=True)

    # 6. Outliers (after unit conversion)
    if len(d):
        days = d["date"].to_numpy().astype("datetime64[D]").astype(np.int64)
        prices = d["price"].to_numpy(dtype=float)
        drop = []
        for i in range(len(d)):
            near = (np.abs(days - days[i]) <= cfg.OUTLIER_WINDOW_DAYS)
            near[i] = False
            if near.sum() >= cfg.OUTLIER_MIN_NEIGHBOURS:
                med = float(np.median(prices[near]))
                if prices[i] > cfg.OUTLIER_HIGH * med or prices[i] < cfg.OUTLIER_LOW * med:
                    drop.append(i)
        if drop:
            flags["outlier"] = len(drop)
            months = ", ".join(d.loc[drop, "date"].dt.strftime("%Y-%m"))
            rep.actions.append(f"Removed {len(drop)} implausible price(s): {months}.")
            d = d.drop(index=drop).reset_index(drop=True)

    rep.rows_kept = len(d)
    rep.clean = d
    if d.empty:
        rep.excluded_reason = "no usable rows after cleaning"
        return rep

    # 7. Freshness. A date or cadence that cannot be read means freshness cannot be proved: treat it as stale.
    cadence = pd.to_numeric(reg_row["update_cadence_days"], errors="coerce")
    unknown = ("no last-updated date in the registry" if pd.isna(updated) else
               "no positive update cadence in the registry" if pd.isna(cadence) or cadence <= 0 else None)
    if unknown:
        flags["stale_data"] = 1
        rep.excluded_reason = f"stale: freshness unknown ({unknown})"
        rep.actions.append("Excluded: " + rep.excluded_reason + ".")
        return rep
    age = (as_of - updated).days
    if age < 0:
        rep.excluded_reason = (f"registry says it was last updated on {rep.last_updated}, "
                               f"after the as-of date {as_of:%Y-%m-%d}")
        rep.actions.append("Excluded: " + rep.excluded_reason + ".")
        return rep
    cadence = float(cadence)
    data_old = d["date"].max() < as_of - pd.DateOffset(months=cfg.MAX_DATA_AGE_MONTHS)
    if age > cfg.STALE_FACTOR * cadence or data_old:
        flags["stale_data"] = 1
        rep.excluded_reason = (f"stale: last updated {age} days ago (cadence {int(cadence)} days), "
                               f"latest data {d['date'].max():%Y-%m}")
        rep.actions.append("Excluded: " + rep.excluded_reason + ".")
        return rep
    if age > cfg.AGING_FACTOR * cadence:
        flags["aging_data"] = 1
        rep.actions.append(f"Kept but aging: last updated {age} days ago.")
    rep.usable = True
    return rep


def _disagreement(primary: pd.DataFrame, other: pd.DataFrame, mk_p: float, mk_o: float,
                  cfg: Config) -> Optional[float]:
    m = primary[["date", "price"]].merge(other[["date", "price"]], on="date", suffixes=("_p", "_o"))
    m = m.sort_values("date").tail(cfg.DISAGREEMENT_MONTHS)
    if len(m) < cfg.DISAGREEMENT_MIN_OVERLAP:
        return None
    dev = ((m["price_o"] / mk_o) / (m["price_p"] / mk_p) - 1).abs()
    return float(dev.median()) * 100


def run_gate(cfg: Config, registry: pd.DataFrame, raws: dict, source_ids: list[str], species: str,
             region: str, as_of: pd.Timestamp, catalog: pd.DataFrame,
             primary_hint: Optional[str] = None) -> GateReport:
    series = f"{species}|{region}"
    reports = {sid: gate_source(raws[sid], registry.loc[sid], species, region, cfg, as_of, catalog)
               for sid in source_ids}
    rep = GateReport(series=series, sources=reports)
    usable = [s for s in source_ids if reports[s].usable]
    # highest tier first; the plan's primary wins ties; then plan order
    usable.sort(key=lambda s: (-TIER_RANK[reports[s].tier], s != primary_hint, source_ids.index(s)))
    rep.usable_ids = usable

    flags: dict = {}
    stale = [s for s in source_ids if "stale_data" in reports[s].flags]
    if stale:
        flags["stale_data"] = len(stale)
    # a selected source that has rows for the series but was thrown out for any reason other than age
    rejected = [s for s in source_ids if reports[s].covers and not reports[s].usable and s not in stale]
    if rejected:
        flags["source_rejected"] = len(rejected)
    for s in usable:
        for k, v in reports[s].flags.items():
            flags[k] = flags.get(k, 0) + v

    if not usable:
        rep.hard_failure = True
        rep.failure_reasons = ["no source had usable rows for this series: " + "; ".join(
            f"{s}: {reports[s].excluded_reason}" for s in source_ids)]
        rep.series_flags = flags
        return rep

    rep.primary_id = usable[0]
    rep.clean = reports[rep.primary_id].clean
    # 8. Cross-source agreement (price only)
    mk_p = float(registry.loc[rep.primary_id, "expected_markup_vs_first_sale"])
    for s in usable[1:]:
        if str(registry.loc[s, "price_basis"]) == "retail":
            continue   # consumer prices swing less than trade prices: reported on their own, not cross-checked
        mk_o = float(registry.loc[s, "expected_markup_vs_first_sale"])
        dev = _disagreement(rep.clean, reports[s].clean, mk_p, mk_o, cfg)
        if dev is None:
            flags["not_cross_checked"] = flags.get("not_cross_checked", 0) + 1
            rep.not_compared.append([rep.primary_id, s])
        elif dev > cfg.DISAGREEMENT_MEDIAN_PCT:
            flags["source_disagreement"] = flags.get("source_disagreement", 0) + 1
            rep.disagreements.append({"pair": [rep.primary_id, s], "median_abs_dev_pct": round(dev, 1)})
    # 9. Source count
    if len([s for s in usable if str(registry.loc[s, "price_basis"]) != "retail"]) == 1:
        flags["single_source"] = 1
    rep.series_flags = flags

    if len(rep.clean) < cfg.MIN_CLEAN_MONTHS:
        rep.hard_failure = True
        rep.failure_reasons = [f"primary source {rep.primary_id} has only {len(rep.clean)} clean months "
                               f"(need {cfg.MIN_CLEAN_MONTHS})"]
    return rep
