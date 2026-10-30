"""Python-only calculations for the new question types and panels. No model sees raw rows; every number
here becomes a numbered statistic in questions.py. Formulas are written out in the dataset README."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import note as note_mod
from .analytics import MONTHS, seasonal_index
from .config import Config, DEFAULT
from .loader import Overrides, load_dataset, load_reference

COST_ALIAS = {"fuel": "diesel_usd_per_gal", "bait": "bait_usd_per_lb", "ice": "ice_usd_per_ton",
              "feed": "feed_finfish_usd_per_ton", "labor": "labor_index", "packaging": "packaging_index"}
GRADE_RANK = {"A": 3, "B": 2, "C": 1}
BUYER_LABELS: dict[str, str] = {}


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


class Extras:
    """Auxiliary tables, loaded once per run (overrides may replace the planted ones)."""

    def __init__(self, cfg: Config = DEFAULT, overrides: Optional[Overrides] = None):
        self.cfg = cfg
        self.markets = load_dataset(cfg, "markets", overrides).set_index("market_id", drop=False)
        self.mprices = _dates(load_dataset(cfg, "market_prices", overrides))
        self.mprices["price"] = pd.to_numeric(self.mprices["price"], errors="coerce")
        self.quality = _dates(load_dataset(cfg, "quality_records", overrides))
        self.quality["freshness_days"] = pd.to_numeric(self.quality["freshness_days"], errors="coerce")
        self.costs = _dates(load_dataset(cfg, "input_costs", overrides))
        self.costs["value"] = pd.to_numeric(self.costs["value"], errors="coerce")
        self.freight = load_reference(cfg, "freight_costs")
        self.storage = load_reference(cfg, "storage_profiles")
        self.seasons = load_reference(cfg, "fishing_seasons")
        self.fx = _dates(load_reference(cfg, "fx_rates").rename(columns={"month": "date"}))
        self.buyers = load_reference(cfg, "customer_channels").set_index("buyer_type", drop=False)

    def add_generated(self, parts: list[dict]) -> None:
        """Generated scenario rows (scenario_species.generate) for species-region pairs with no hand-made data."""
        if not parts:
            return
        self.seasons = pd.concat([self.seasons] + [p["season"] for p in parts], ignore_index=True)
        self.storage = pd.concat([self.storage] + [p["storage"] for p in parts], ignore_index=True)
        mp = _dates(pd.concat([p["market_prices"] for p in parts], ignore_index=True))
        if len(mp):
            mp["price"] = pd.to_numeric(mp["price"], errors="coerce")
            self.mprices = pd.concat([self.mprices, mp], ignore_index=True)
        q = _dates(pd.concat([p["quality"] for p in parts], ignore_index=True))
        if len(q):
            q["freshness_days"] = pd.to_numeric(q["freshness_days"], errors="coerce")
            self.quality = pd.concat([self.quality, q], ignore_index=True)

    # ---------------------------------------------------------------- quality
    def quality_summary(self, species: str, region: str, as_of: pd.Timestamp) -> dict:
        q = self.quality
        w = q[(q["species"] == species) & (q["region"] == region)]
        notes = [str(x) for x in w["notes"]] if "notes" in w else []
        injected = sorted({p for n in notes for p in note_mod.matched_injection(n)})
        w = w[(w["date"] >= pd.Timestamp(self.cfg.QUALITY_WINDOW_START)) & (w["date"] <= as_of)]
        n = len(w)
        flags: list[str] = []
        if injected:
            flags.append("untrusted_text_ignored")
        if n == 0:
            return {"status": "none", "n": 0, "verified_share": None, "modal_grade": None,
                    "verified_modal_grade": None, "median_freshness_days": None, "flags": flags,
                    "injection_phrases": injected}
        share = float((w["verification_status"] == "VERIFIED").mean())
        if (w["verification_status"] == "CONFLICTED").any():
            status = "conflicted"; flags.append("quality_conflicted")
        elif share >= self.cfg.QUALITY_VERIFIED_SHARE:
            status = "verified"
        elif share >= self.cfg.QUALITY_PARTIAL_SHARE:
            status = "partial"
        else:
            status = "unverified"
        if status == "unverified":
            flags.append("quality_unverified")

        def modal(x: pd.DataFrame) -> Optional[str]:
            if x.empty:
                return None
            c = x["grade"].value_counts()
            return sorted(c[c == c.max()].index, key=lambda g: -GRADE_RANK.get(g, 0))[0]

        return {"status": status, "n": n, "verified_share": share, "modal_grade": modal(w),
                "verified_modal_grade": modal(w[w["verification_status"] == "VERIFIED"]),
                "median_freshness_days": float(w["freshness_days"].median()), "flags": flags,
                "injection_phrases": injected}

    # ---------------------------------------------------------------- freight, storage, seasons
    def freight_cost(self, a: str, b: str, form: str = "chilled") -> float:
        r = self.freight[(self.freight["from_region"] == a) & (self.freight["to_region"] == b)].iloc[0]
        return float(r["chilled_usd_per_lb" if form == "chilled" else "frozen_usd_per_lb"])

    def hold_economics(self, species: str, ratio: float, months_to_best: int, storage: str) -> Optional[dict]:
        if storage not in ("chilled", "frozen"):
            return None
        p = self.storage[(self.storage["species"] == species) & (self.storage["form"] == storage)]
        if p.empty:
            return None
        p = p.iloc[0]
        k = months_to_best
        net = (ratio - 1) * 100 - (float(p["carrying_cost_pct_per_month"]) + float(p["shrink_pct_per_month"])) * k
        return {"net_gain_pct": net, "shelf_exceeded": bool(float(p["max_shelf_days"]) < 30 * k), "months": k,
                "shelf_days": int(p["max_shelf_days"])}

    def open_months(self, species: str, region: str) -> list[int]:
        r = self.seasons[(self.seasons["species"] == species) & (self.seasons["region"] == region)]
        if r.empty:
            return list(range(1, 13))
        return [int(x) for x in str(r.iloc[0]["open_months"]).split(";")]

    # ---------------------------------------------------------------- best months
    def best_months(self, clean: pd.DataFrame, species: str, region: str, wild: bool, as_of: pd.Timestamp) -> Optional[dict]:
        pi = seasonal_index(clean, as_of, "price")
        if pi is None:
            return None
        vi = seasonal_index(clean, as_of, "volume") if wild else None
        if wild and vi is None:
            return None
        open_m = self.open_months(species, region)
        e = self.cfg.SEASON_VOL_EXPONENT
        score = {m: pi[m - 1] * ((vi[m - 1] ** e) if wild else 1.0) for m in open_m}
        order = sorted(score, key=lambda m: (-score[m], m))
        return {"top": [(MONTHS[m - 1], score[m]) for m in order[:3]], "open": [MONTHS[m - 1] for m in open_m],
                "gap_3rd_4th": (score[order[2]] - score[order[3]]) if len(order) > 3 else None,
                "uses_volume": wild}

    # ---------------------------------------------------------------- markets
    def market_comparison(self, species: str, user_region: str, as_of: pd.Timestamp) -> dict:
        mp = self.mprices[self.mprices["species"] == species].copy()
        flags: list[str] = []
        non_usd = mp["currency"].astype(str) != "USD"
        if non_usd.any():
            fx = self.fx.set_index(["currency", "date"])["usd_per_unit"]
            conv = []
            for i, r in mp[non_usd].iterrows():
                try:
                    conv.append((i, float(r["price"]) * float(fx.loc[(r["currency"], r["date"])])))
                except KeyError:
                    conv.append((i, np.nan))
            for i, v in conv:
                mp.loc[i, "price"] = v
            mp = mp.dropna(subset=["price"])
            flags.append("currency_mismatch")
        ranked, excluded = [], []
        for mid, g in mp.groupby("market_id"):
            if mid not in self.markets.index:
                continue
            meta = self.markets.loc[mid]
            age = (as_of - pd.Timestamp(meta["last_updated"])).days
            last = g["date"].max()
            m3 = g[g["date"] > last - pd.DateOffset(months=3)]
            price = float(m3["price"].mean())
            fee = float(meta["fee_pct"])
            freight = self.freight_cost(user_region, str(meta["region"]))
            row = {"market_id": mid, "name": str(meta["name"]), "region": str(meta["region"]), "mean3_price": price,
                   "fee_pct": fee, "freight": freight, "net_price": price * (1 - fee / 100) - freight,
                   "age_days": age, "trust_tier": str(meta["trust_tier"])}
            if age <= self.cfg.MARKET_STALE_FACTOR * float(meta["update_cadence_days"]):
                ranked.append(row)
            else:
                excluded.append({**row, "reason": f"last posted {age} days ago (weekly cadence)"})
                if "stale_data" not in flags:
                    flags.append("stale_data")
        ranked.sort(key=lambda r: -r["net_price"])
        gap = ((ranked[0]["net_price"] - ranked[1]["net_price"]) / ranked[0]["net_price"]) if len(ranked) > 1 else None
        return {"ranking": ranked, "excluded": excluded, "gap": gap, "flags": flags}

    # ---------------------------------------------------------------- buyers
    def best_buyer(self, base_price: float, source_type: str, category: str, segment: str, volume: float,
                   quality: dict) -> dict:
        grade = quality.get("verified_modal_grade")
        flags: list[str] = []
        if grade is None:
            grade = "C"; flags.append("grade_assumed")
        col = f"mult_{category}_species"
        rows, excluded = [], {}
        for b in self.buyers.itertuples():
            if b.applies_to not in ("any", source_type):
                excluded[b.buyer_type] = "not applicable to this kind of product"; continue
            if volume < float(b.min_order_lb):
                excluded[b.buyer_type] = "your volume is below their minimum order"; continue
            if GRADE_RANK.get(grade, 1) < GRADE_RANK[b.min_grade]:
                excluded[b.buyer_type] = "they need a higher verified grade"; continue
            net = base_price * float(getattr(b, col)) * (1 - float(b.fee_pct) / 100) * \
                (1 - float(b.payment_days) / 365 * self.cfg.CARRY_APR)
            rows.append({"buyer_type": b.buyer_type, "label": b.label, "net_price": net,
                         "segment_fit": segment in str(b.segment_fit).split(";"), "payment_days": int(b.payment_days)})
        fit = [r for r in rows if r["segment_fit"]]
        pool = sorted(fit if fit else rows, key=lambda r: -r["net_price"])
        gap = ((pool[0]["net_price"] - pool[1]["net_price"]) / pool[0]["net_price"]) if len(pool) > 1 else None
        return {"ranking": pool[:3], "excluded": excluded, "used_segment_fit": bool(fit), "gap": gap,
                "grade_used": grade, "grade_verified": quality.get("verified_modal_grade") is not None,
                "flags": flags}

    # ---------------------------------------------------------------- costs
    def cost_pressure(self, region: str, cost_types: list[str], as_of: pd.Timestamp) -> dict:
        per, incomplete = {}, []
        for c in cost_types:
            name = COST_ALIAS.get(c, c)
            d = self.costs[(self.costs["region"] == region) & (self.costs["cost_type"] == name)]
            d = d[d["date"] <= as_of].sort_values("date")
            if d.empty:
                incomplete.append(name); continue
            last = d["date"].max()
            cur = d[(d["date"] > last - pd.DateOffset(months=12)) & (d["date"] <= last)]
            prev = d[(d["date"] > last - pd.DateOffset(months=24)) & (d["date"] <= last - pd.DateOffset(months=12))]
            if len(cur) >= 9 and len(prev) >= 9:
                per[name] = (cur["value"].mean() / prev["value"].mean() - 1) * 100
            else:
                incomplete.append(name)
        top = max(per, key=per.get) if per else None
        return {"per_type": per, "incomplete": incomplete, "top_type": top, "top": per[top] if top else None,
                "flags": ["cost_data_incomplete"] if incomplete else []}
