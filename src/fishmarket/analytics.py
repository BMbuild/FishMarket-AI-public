"""Step 4: analytics engine. Python computes every statistic; models only interpret them."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .config import Config, DEFAULT
from .schemas import StatRow

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def seasonal_index(clean: pd.DataFrame, as_of: pd.Timestamp, col: str = "price") -> Optional[list[float]]:
    """Per complete calendar year before as_of's year: price / that year's mean, then average by month."""
    d = clean.copy()
    d["y"], d["m"] = d["date"].dt.year, d["date"].dt.month
    ratios = []
    for y in sorted(d["y"].unique()):
        s = d[d["y"] == y]
        if y < as_of.year and s["m"].nunique() == 12:
            ratios.append(s.groupby("m")[col].mean() / s[col].mean())
    if not ratios:
        return None
    return pd.concat(ratios, axis=1).mean(axis=1).reindex(range(1, 13)).tolist()


def _window(s: pd.DataFrame, last: pd.Timestamp, lo: int, hi: int) -> pd.DataFrame:
    return s[(s["date"] > last - pd.DateOffset(months=hi)) & (s["date"] <= last - pd.DateOffset(months=lo))]


def compute_stats(clean: pd.DataFrame, series: str, source_id: str, as_of: pd.Timestamp,
                  cfg: Config = DEFAULT) -> dict:
    """Returns {"stats": [StatRow], "seasonal_index": [12 floats] | None, "history": [...]}.
    Unavailable statistics are simply omitted."""
    rows: list[StatRow] = []

    def add(kind, value, unit, month=None, reliability=None, window="", n=0):
        rows.append(StatRow(id=f"S{len(rows) + 1}", series=series, kind=kind, value=float(value), unit=unit,
                            month=month, reliability=reliability, window=window, source_id=source_id,
                            n_obs=int(n)))

    s = clean.sort_values("date")
    idx = seasonal_index(s, as_of)
    if idx is not None:
        now = as_of.month - 1
        nxt = [(now + k) % 12 for k in (1, 2, 3)]
        best_i = max(nxt, key=lambda i: idx[i])
        spread = max(idx) - min(idx)
        peak = int(np.argmax(idx))
        n_years = s[s["date"].dt.year < as_of.year].groupby(s["date"].dt.year).size().eq(12).sum()
        win = f"complete calendar years before {as_of.year}"
        add("seasonal_index_now", idx[now], "index", MONTHS[now], None, win, n_years)
        add("seasonal_index_best_next3", idx[best_i], "index", MONTHS[best_i], None, win, n_years)
        add("best_next3_vs_now_ratio", idx[best_i] / idx[now], "ratio", MONTHS[best_i], None, win, n_years)
        add("seasonal_peak_month", idx[peak], "index", MONTHS[peak],
            "strong" if spread >= cfg.SEASONALITY_STRONG_SPREAD else "weak", win, n_years)

    last = s["date"].max()
    cur, prev = _window(s, last, 0, 12), _window(s, last, 12, 24)
    if len(cur) >= 9 and len(prev) >= 9:
        add("yoy_price_change_pct", (cur["price"].mean() / prev["price"].mean() - 1) * 100, "percent",
            window="latest 12 months vs the 12 before", n=len(cur) + len(prev))
    l3 = _window(s, last, 0, 3)
    p3 = s[(s["date"] > last - pd.DateOffset(months=15)) & (s["date"] <= last - pd.DateOffset(months=12))]
    lv, pv = l3["volume"].dropna(), p3["volume"].dropna()
    if len(lv) and len(pv):
        add("supply_yoy_change_pct", (lv.mean() / pv.mean() - 1) * 100, "percent",
            window="latest 3 months vs the same 3 a year earlier", n=len(lv) + len(pv))
    add("latest_price", s.iloc[-1]["price"], "usd_per_lb", f"{MONTHS[last.month - 1]} {last.year}",
        window="latest data month", n=1)

    history = [{"date": d.strftime("%Y-%m-%d"), "price": float(p)} for d, p in zip(s["date"], s["price"])]
    return {"stats": rows, "seasonal_index": idx, "history": history}


def stat_by_kind(stats: list[StatRow], kind: str) -> Optional[StatRow]:
    return next((x for x in stats if x.kind == kind), None)
