"""Question-type logic. Python computes every statistic and sets the direction or ranking; the analyst only
explains. One `SpeciesResult` per species, merged into one numbered statistics table."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .analytics import MONTHS, compute_stats
from .config import Config, DEFAULT
from .extras import Extras
from .schemas import StatRow

RANK_KINDS = {"best_month_score", "market_net_price", "buyer_net_price"}
CHANNEL_SOURCE = {"wholesale": "SRC-IND-01", "retail": "SRC-RTL-01"}


@dataclass
class SpeciesResult:
    species: str
    series: str
    channel: str = "first_sale"
    source_id: str = ""
    stats: list = field(default_factory=list)       # StatRow, ids provisional
    seasonal_index: Optional[list] = None
    history: list = field(default_factory=list)
    flags: set = field(default_factory=set)         # extra flags (do not change trust)
    tables: dict = field(default_factory=dict)      # structured results for the report
    quality: dict = field(default_factory=dict)


def operation_channel(op_row, qtype: str) -> str:
    ch = {"sell_or_hold": op_row.get("sell_channel"), "best_buyer_type": op_row.get("sell_channel"),
          "buy_now_or_wait": op_row.get("buy_channel")}.get(qtype)
    return ch if isinstance(ch, str) and ch in ("first_sale", "wholesale", "retail") else "first_sale"


def pick_channel_series(channel: str, gate) -> tuple[str, str, bool]:
    """(channel actually used, source id, fell_back)."""
    if channel == "first_sale":
        return "first_sale", gate.primary_id, False
    sid = CHANNEL_SOURCE[channel]
    rep = gate.sources.get(sid)
    if rep is not None and rep.usable and rep.clean is not None and len(rep.clean) >= 24:
        return channel, sid, False
    return "first_sale", gate.primary_id, True


def _row(rows: list, series: str, source: str, kind: str, value: float, unit: str, label: str = "",
         month: Optional[str] = None, reliability: Optional[str] = None, window: str = "", n: int = 0) -> None:
    rows.append(StatRow(id=f"T{len(rows) + 1}", series=series, kind=kind, value=float(value), unit=unit,
                        label=label, month=month, reliability=reliability, window=window,
                        source_id=source, n_obs=int(n)))


def _spread(a: pd.DataFrame, b: pd.DataFrame) -> Optional[tuple[float, float]]:
    m = a[["date", "price"]].merge(b[["date", "price"]], on="date", suffixes=("_s", "_b")).sort_values("date")
    if len(m) < 15:
        return None
    l3, p3 = m.tail(3), m.iloc[-15:-12]
    cur = (l3["price_s"].mean() / l3["price_b"].mean() - 1) * 100
    prev = (p3["price_s"].mean() / p3["price_b"].mean() - 1) * 100
    return cur, cur - prev


def analyse_species(species: str, prof, gate, registry, catalog, ex: Extras, as_of: pd.Timestamp,
                    op_row: dict, cfg: Config = DEFAULT) -> SpeciesResult:
    region, qtype = prof.region, prof.question_type
    series = f"{species}|{region}"
    want = operation_channel(op_row, qtype)
    chan, sid, fell = pick_channel_series(want, gate)
    clean = gate.sources[sid].clean if sid in gate.sources and gate.sources[sid].clean is not None else gate.clean
    res = SpeciesResult(species=species, series=series, channel=chan, source_id=sid)
    if fell:
        res.flags.add("channel_fallback")
    an = compute_stats(clean, series, sid, as_of, cfg)
    res.stats = list(an["stats"])
    res.seasonal_index, res.history = an["seasonal_index"], an["history"]
    rows = res.stats
    idx = an["seasonal_index"]
    source_type = str(catalog.loc[species, "source_type"])
    category = str(catalog.loc[species, "category"])

    def add(kind, value, unit, **kw):
        rows.append(StatRow(id=f"T{len(rows) + 1}", series=series, kind=kind, value=float(value), unit=unit,
                            source_id=kw.pop("source", sid), **{k: v for k, v in kw.items()}))

    # --- quality panel (all question types)
    q = ex.quality_summary(species, region, as_of)
    res.quality = q
    res.flags |= set(q["flags"])
    if q["n"]:
        add("quality_verified_share_pct", q["verified_share"] * 100, "percent", window="quality records since the window start", n_obs=q["n"])
        add("quality_median_freshness_days", q["median_freshness_days"], "days", window="same records", n_obs=q["n"])

    ratio = next((s.value for s in rows if s.kind == "best_next3_vs_now_ratio"), None)
    now = as_of.month - 1
    if qtype == "sell_or_hold":
        add("rule_hold_threshold", cfg.HOLD_THRESHOLD, "ratio", label="decision rule")
        add("rule_trend_threshold_pct", cfg.TREND_THRESHOLD_PCT, "percent", label="decision rule")
        if ratio is not None and ratio >= cfg.HOLD_THRESHOLD and idx is not None:
            nxt = [(now + k) % 12 for k in (1, 2, 3)]
            bi = max(nxt, key=lambda i: idx[i])
            k = (bi - now) % 12
            h = ex.hold_economics(species, ratio, k, prof.storage)
            if h is None:
                res.flags.add("no_storage_info")
            else:
                add("hold_net_gain_pct", h["net_gain_pct"], "percent", label=prof.storage,
                    window=f"after storage cost and shrink over {k} months")
                res.tables["hold"] = {"net_gain_pct": h["net_gain_pct"], "shelf_exceeded": h["shelf_exceeded"],
                                      "months": k, "storage": prof.storage, "shelf_days": h["shelf_days"]}
                if h["shelf_exceeded"]:
                    res.flags.add("shelf_life_exceeded")
        # channel spread for operations that buy and sell
        sell_ch, buy_ch = op_row.get("sell_channel"), op_row.get("buy_channel")
        if isinstance(sell_ch, str) and isinstance(buy_ch, str) and sell_ch and buy_ch:
            ids = {"first_sale": gate.primary_id, "wholesale": "SRC-IND-01", "retail": "SRC-RTL-01"}
            a, b = gate.sources.get(ids[sell_ch]), gate.sources.get(ids[buy_ch])
            if a is not None and b is not None and a.usable and b.usable:
                sp = _spread(a.clean, b.clean)
                if sp:
                    add("channel_spread_pct", sp[0], "percent", label=f"{sell_ch} vs {buy_ch}", window="latest 3 months")
                    add("channel_spread_yoy_pts", sp[1], "points", label=f"{sell_ch} vs {buy_ch}",
                        window="vs the same 3 months a year earlier")
        # input costs
        costs = list(op_row.get("costs") or [])
        if costs:
            cp = ex.cost_pressure(region, costs, as_of)
            res.flags |= set(cp["flags"])
            for name, v in cp["per_type"].items():
                add("cost_yoy_pct", v, "percent", label=name, window="latest 12 months vs the 12 before")
            y = next((s.value for s in rows if s.kind == "yoy_price_change_pct"), None)
            squeeze = None
            if cp["top"] is not None and y is not None:
                gap = cp["top"] - y
                add("margin_squeeze_gap_pts", gap, "points", label=cp["top_type"],
                    window="largest cost change minus price change")
                add("rule_squeeze_threshold_pts", cfg.SQUEEZE_PTS, "points", label="decision rule")
                squeeze = gap >= cfg.SQUEEZE_PTS
                if squeeze:
                    res.flags.add("margin_squeeze")
            res.tables["costs"] = {"per_type": cp["per_type"], "incomplete": cp["incomplete"],
                                   "top_type": cp["top_type"], "squeeze": squeeze}
    elif qtype == "buy_now_or_wait" and idx is not None:
        nxt = [(now + k) % 12 for k in (1, 2, 3)]
        m3 = float(np.mean([idx[i] for i in nxt])) / idx[now]
        add("next3_mean_vs_now_ratio", m3, "ratio", window="mean of the next 3 months' index over this month's")
        add("rule_buy_threshold", cfg.BUY_THRESHOLD, "ratio", label="decision rule")
        add("rule_wait_threshold", cfg.WAIT_THRESHOLD, "ratio", label="decision rule")
    elif qtype == "best_months":
        bm = ex.best_months(clean, species, region, source_type == "wild_catch", as_of)
        if bm:
            for name, score in bm["top"]:
                add("best_month_score", score, "score", label=name, month=name,
                    window="price index x volume index^0.5 (wild) or price index (farmed), open months only")
            add("open_season_months", len(bm["open"]), "months", window="open-season months in this region")
            res.tables["best_months"] = bm
    elif qtype == "compare_markets":
        cm = ex.market_comparison(species, region, as_of)
        res.flags |= set(cm["flags"])
        for r in cm["ranking"][:3]:
            add("market_net_price", r["net_price"], "usd_per_lb", label=r["name"], source="SRC-MKT-01",
                window="3-month mean x (1 - fee) - freight from your region")
        for r in cm["excluded"]:
            add("market_age_days", r["age_days"], "days", label=r["name"], source="SRC-MKT-01",
                window="days since the market last posted")
        if cm["gap"] is not None:
            add("net_price_gap_pct", cm["gap"] * 100, "percent", source="SRC-MKT-01", window="best vs second best")
        res.tables["markets"] = cm
    elif qtype == "best_buyer_type":
        base = float(gate.clean.sort_values("date").tail(3)["price"].mean())
        bb = ex.best_buyer(base, source_type, category, prof.customer_segment, prof.volume_lb_per_month, q)
        res.flags |= set(bb["flags"])
        add("buyer_base_price", base, "usd_per_lb", window="latest 3 months, first-sale")
        for r in bb["ranking"]:
            add("buyer_net_price", r["net_price"], "usd_per_lb", label=r["label"], window="after fees and payment delay")
        if bb["gap"] is not None:
            add("net_price_gap_pct", bb["gap"] * 100, "percent", window="best vs second best")
        res.tables["buyers"] = bb
    return res


def merge(results: list[SpeciesResult]) -> list[StatRow]:
    """One table, ids S1..Sn in a stable order."""
    out: list[StatRow] = []
    for r in results:
        for s in r.stats:
            out.append(s.model_copy(update={"id": f"S{len(out) + 1}"}))
    return out


def decide(stats: list[StatRow], qtype: str, cfg: Config = DEFAULT) -> dict:
    """Direction per series, and one overall direction ('per_species' when there are several)."""
    series = list(dict.fromkeys(s.series for s in stats))
    per = {}
    for ser in series:
        rows = [s for s in stats if s.series == ser]
        per[ser] = _direction(rows, qtype, cfg)
    overall = per[series[0]] if len(series) == 1 else "per_species"
    return {"direction": overall, "by_series": per}


def _direction(rows: list[StatRow], qtype: str, cfg: Config) -> str:
    def val(kind):
        r = next((s for s in rows if s.kind == kind), None)
        return None if r is None else r.value
    if qtype == "sell_or_hold":
        v = val("best_next3_vs_now_ratio")
        return "insufficient_data" if v is None else ("hold" if v >= cfg.HOLD_THRESHOLD else "sell_now")
    if qtype == "buy_now_or_wait":
        v = val("next3_mean_vs_now_ratio")
        if v is None:
            return "insufficient_data"
        return "buy_now" if v >= cfg.BUY_THRESHOLD else "wait" if v <= cfg.WAIT_THRESHOLD else "no_clear_signal"
    return "ranking" if any(s.kind in RANK_KINDS for s in rows) else "insufficient_data"
