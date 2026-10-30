"""Real NOAA Fisheries One Stop Shop (FOSS) commercial landings: loader, cleaning and deterministic analytics.

Honest scope: this data is ANNUAL, by state and region, and gives dockside (first-sale) value only.
It has no monthly prices, no markets, no quality or cost data. So the real-data mode answers a
different set of questions than the fictional monthly demo: long-run ex-vessel price trend, volatility,
volume trend, and which region paid the most. All numbers are computed here in Python; any AI
sentence only explains them (same rule as the rest of the app).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import cleansing

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = Path(os.environ.get("FISHMARKET_REAL_CSV", ROOT / "noaa_landings_full.csv"))

MIN_YEARS_FOR_TREND = 5
RECENT_YEARS = 5
SOURCE_LABEL = "NOAA Fisheries FOSS commercial landings (annual, ex-vessel)"


def clean_name(n: str) -> str:
    """'COD, PACIFIC' -> 'Pacific cod'; 'SHRIMP, BROWN' -> 'Brown shrimp'. Drops NOAA's '**' roll-up marker."""
    n = str(n).replace("**", "").strip()
    if "," in n:
        head, tail = n.split(",", 1)
        n = f"{tail.strip()} {head.strip()}"
    return n.lower().capitalize()


@dataclass
class Loaded:
    df: pd.DataFrame          # clean commercial rows, one per species x region x year
    notes: dict               # counts of what was dropped and why
    path: str
    states: pd.DataFrame | None = None   # same, one row per species x state x year
    rec: pd.DataFrame | None = None      # recreational (MRIP) catch, pounds and fish counts, no dollars
    classified: pd.DataFrame | None = None   # every raw row with status and reasons (the gate's full output)


def load(path: str | Path | None = None) -> Loaded:
    """Reads the NOAA csv through the validation gate (cleansing.py). Only VALID rows reach analysis."""
    p = Path(path or DEFAULT_CSV)
    raw = pd.read_csv(p, low_memory=False)
    cls = cleansing.classify(raw)
    rep = cleansing.report(cls)
    parts = cleansing.split(cls)
    notes = {"rows_read": rep["total_rows"], "gate": rep, "review_rows_held_back": int(len(parts["review"])),
             "rejected_rows": int(len(parts["rejected"])), "excluded_by_design_rows": int(len(parts["excluded"]))}
    c = parts["valid_commercial"].assign(species=lambda x: x["ts_afs_name"].map(clean_name))
    st = (c.groupby(["species", "region_name", "state_name", "year"], as_index=False)
            .agg(pounds=("pounds", "sum"), dollars=("dollars", "sum")))
    st["price"] = st["dollars"] / st["pounds"]
    st = st.rename(columns={"region_name": "region"})
    st["state"] = st["state_name"].str.title()
    st["year"] = st["year"].astype(int)
    rc = parts["valid_recreational"]
    rc = rc.assign(species=rc["ts_afs_name"].map(clean_name), region=rc["region_name"].fillna("Unassigned"))
    rec = (rc.groupby(["species", "region", "year"], as_index=False)
             .agg(pounds=("pounds", "sum"), fish=("tot_count", "sum")))
    rec["year"] = rec["year"].astype(int)
    g = (c.groupby(["species", "region_name", "year"], as_index=False)
           .agg(pounds=("pounds", "sum"), dollars=("dollars", "sum"),
                scientific=("ts_scientific_name", "first"), sources=("source", lambda x: ",".join(sorted(set(x)))),
                ts_afs_name=("ts_afs_name", "first")))
    g["price"] = g["dollars"] / g["pounds"]
    g["region"] = g["region_name"]
    g["year"] = g["year"].astype(int)
    return Loaded(g[["species", "region", "year", "pounds", "dollars", "price", "scientific", "sources", "ts_afs_name"]],
                  notes, str(p), st[["species", "region", "state", "year", "pounds", "dollars", "price"]], rec, cls)


def species_list(df: pd.DataFrame, min_years: int = 10, recent_from: int | None = None) -> list[str]:
    """Species with enough history to analyse, biggest first by recent pounds."""
    last = int(df["year"].max())
    recent_from = recent_from or last - RECENT_YEARS + 1
    ok = df.groupby("species")["year"].nunique()
    ok = ok[ok >= min_years].index
    r = df[(df["species"].isin(ok)) & (df["year"] >= recent_from)]
    return list(r.groupby("species")["pounds"].sum().sort_values(ascending=False).index)


def regions_for(df: pd.DataFrame, species: str) -> list[str]:
    d = df[df["species"] == species]
    return list(d.groupby("region")["pounds"].sum().sort_values(ascending=False).index)


def series(df: pd.DataFrame, species: str, region: str | None = None) -> pd.DataFrame:
    """Annual price and volume for a species, nationally (region=None) or in one region."""
    d = df[df["species"] == species]
    if region and region != "All regions":
        d = d[d["region"] == region]
    s = d.groupby("year", as_index=False).agg(pounds=("pounds", "sum"), dollars=("dollars", "sum"))
    s["price"] = s["dollars"] / s["pounds"]
    return s.sort_values("year").reset_index(drop=True)


def _cagr(first: float, last: float, years: int) -> float | None:
    return None if years <= 0 or first <= 0 else (last / first) ** (1 / years) - 1


def analyse(df: pd.DataFrame, species: str, region: str | None = None) -> dict:
    """Deterministic facts about one species/region. Every claim carries the numbers behind it."""
    s = series(df, species, region)
    out = {"species": species, "region": region or "All regions", "source": SOURCE_LABEL, "unit": "USD per lb, annual ex-vessel"}
    if len(s) < 3:
        out.update(ok=False, reason="Fewer than 3 years of usable data.")
        return out
    last_year = int(s["year"].iloc[-1])
    latest = s.iloc[-1]
    prev = s[s["year"] == last_year - 1]
    recent = s[s["year"] > last_year - RECENT_YEARS]
    prior = s[(s["year"] <= last_year - RECENT_YEARS) & (s["year"] > last_year - 2 * RECENT_YEARS)]
    out.update(ok=True, first_year=int(s["year"].iloc[0]), last_year=last_year, years_of_data=int(len(s)),
               latest_price=round(float(latest["price"]), 3), latest_pounds=float(latest["pounds"]),
               latest_dollars=float(latest["dollars"]))
    out["yoy_price_pct"] = round(float(latest["price"] / prev["price"].iloc[0] - 1) * 100, 1) if len(prev) else None
    out["yoy_pounds_pct"] = round(float(latest["pounds"] / prev["pounds"].iloc[0] - 1) * 100, 1) if len(prev) else None
    out["gap_years"] = [int(y) for y in range(int(s["year"].iloc[0]), last_year + 1) if y not in set(s["year"])]
    if len(recent) >= 3:
        out["recent_avg_price"] = round(float(recent["dollars"].sum() / recent["pounds"].sum()), 3)
        out["latest_vs_recent_avg_pct"] = round(float(latest["price"] / out["recent_avg_price"] - 1) * 100, 1)
        cv = float(recent["price"].std(ddof=0) / recent["price"].mean() * 100)
        out["recent_price_volatility_pct"] = round(cv, 1)
        out["volatility_label"] = "high" if cv >= 25 else "moderate" if cv >= 10 else "low"
    if len(prior) >= 3 and len(recent) >= 3:
        out["prior5_avg_price"] = round(float(prior["dollars"].sum() / prior["pounds"].sum()), 3)
        out["recent_vs_prior5_pct"] = round((out["recent_avg_price"] / out["prior5_avg_price"] - 1) * 100, 1)
    if len(recent) >= 3:
        slope = np.polyfit(recent["year"], recent["price"], 1)[0]
        pct = slope / float(recent["price"].mean()) * 100
        out["recent_trend_pct_per_year"] = round(float(pct), 1)
        out["trend_direction"] = "up" if pct > 2 else "down" if pct < -2 else "flat"
    if len(s) >= MIN_YEARS_FOR_TREND:
        yrs = last_year - int(s["year"].iloc[0])
        c = _cagr(float(s["price"].iloc[0]), float(latest["price"]), yrs)
        out["long_run_price_cagr_pct"] = None if c is None else round(c * 100, 1)
    best = s.loc[s["price"].idxmax()]
    out["peak_year"], out["peak_price"] = int(best["year"]), round(float(best["price"]), 3)
    # regional ranking in the latest year with data (only when national view)
    if not region or region == "All regions":
        r = df[(df["species"] == species) & (df["year"] == last_year)]
        rr = r.groupby("region").agg(pounds=("pounds", "sum"), dollars=("dollars", "sum"))
        rr["price"] = rr["dollars"] / rr["pounds"]
        rr = rr[rr["pounds"] >= 0.01 * rr["pounds"].sum()].sort_values("price", ascending=False)
        out["regions_latest_year"] = [{"region": i, "price": round(float(v.price), 3), "pounds": float(v.pounds)}
                                      for i, v in rr.iterrows()]
    out["caveats"] = caveats(out, s)
    out["read"] = headline(out)
    return out


def caveats(a: dict, s: pd.DataFrame) -> list[str]:
    c = ["Annual data: it cannot show which months pay best or what the price will do next month.",
         "Dockside value only: it is not a market, wholesale or retail price, and says nothing about your costs or fees."]
    if a.get("gap_years"):
        c.append("Missing years in this series: " + ", ".join(map(str, a["gap_years"][:8])) + ".")
    if a["years_of_data"] < 10:
        c.append("Short history (under 10 years); treat trends as weak.")
    if a["last_year"] < 2024:
        c.append(f"Latest year available is {a['last_year']}, older than the newest NOAA release.")
    c.append("Prices are not adjusted for inflation.")
    return c


def headline(a: dict) -> str:
    d = {"up": "rising", "down": "falling", "flat": "roughly flat"}.get(a.get("trend_direction"), "unclear")
    bits = [f"{a['species']} ({a['region']}): {a['last_year']} dockside price ${a['latest_price']:.2f}/lb"]
    if a.get("yoy_price_pct") is not None:
        bits.append(f"{a['yoy_price_pct']:+.1f}% vs {a['last_year'] - 1}")
    bits.append(f"5-year trend {d}")
    if a.get("volatility_label"):
        bits.append(f"{a['volatility_label']} year-to-year swings")
    return "; ".join(bits) + "."


def compare_regions(df: pd.DataFrame, species: str, year: int | None = None) -> pd.DataFrame:
    year = year or int(df[df["species"] == species]["year"].max())
    r = df[(df["species"] == species) & (df["year"] == year)]
    g = r.groupby("region", as_index=False).agg(pounds=("pounds", "sum"), dollars=("dollars", "sum"))
    g["price"] = g["dollars"] / g["pounds"]
    return g.sort_values("price", ascending=False).reset_index(drop=True)


def to_kg(price_per_lb: float) -> float:
    return price_per_lb * 2.2046


def provenance(loaded: Loaded) -> dict:
    return {"source": SOURCE_LABEL, "file": Path(loaded.path).name, "cleaning": loaded.notes,
            "price_bounds_usd_per_lb": [cleansing.PRICE_FLOOR, cleansing.PRICE_CEIL]}


# ---------------------------------------------------------------- inflation
CPI_PATH = ROOT / "data_real" / "cpi_u_annual.csv"


def cpi() -> pd.Series:
    """US CPI-U annual average (1982-84=100), indexed by year. Source: BLS (see data_real/README)."""
    d = pd.read_csv(CPI_PATH)
    return d.set_index("year")["cpi_u"]


def add_real_price(df: pd.DataFrame, base_year: int | None = None) -> pd.DataFrame:
    """Adds price_real: the price restated in base-year dollars (default: latest year in the data)."""
    c = cpi()
    base_year = base_year or min(int(df["year"].max()), int(c.index.max()))
    out = df.copy()
    out["price_real"] = out["price"] * c[base_year] / out["year"].map(c)
    out.attrs["base_year"] = base_year
    return out


def real_trend(df: pd.DataFrame, species: str, region: str | None = None) -> dict:
    """Long-run price change with and without inflation, for the same series."""
    s = series(df, species, region)
    s = s[s["year"].isin(cpi().index)]
    if len(s) < MIN_YEARS_FOR_TREND:
        return {"ok": False}
    c = cpi()
    by = int(s["year"].iloc[-1])
    s = s.assign(real=s["price"] * c[by] / s["year"].map(c))
    yrs = by - int(s["year"].iloc[0])
    nom = _cagr(float(s["price"].iloc[0]), float(s["price"].iloc[-1]), yrs)
    rl = _cagr(float(s["real"].iloc[0]), float(s["real"].iloc[-1]), yrs)
    return {"ok": True, "base_year": by, "first_year": int(s["year"].iloc[0]), "nominal_cagr_pct": round(nom * 100, 1),
            "real_cagr_pct": round(rl * 100, 1), "real_series": s[["year", "real"]], "inflation_cagr_pct": round(float((c[by] / c[int(s["year"].iloc[0])]) ** (1 / yrs) - 1) * 100, 1)}


# ---------------------------------------------------------------- browse / rank
def top_species(df: pd.DataFrame, year: int | None = None, by: str = "dollars", n: int = 15) -> pd.DataFrame:
    year = year or int(df["year"].max())
    g = df[df["year"] == year].groupby("species", as_index=False).agg(pounds=("pounds", "sum"), dollars=("dollars", "sum"))
    g["price"] = g["dollars"] / g["pounds"]
    return g.sort_values(by, ascending=False).head(n).reset_index(drop=True)


def movers(df: pd.DataFrame, year: int | None = None, min_dollars: float = 5e6, n: int = 10) -> dict:
    """Biggest dockside price moves vs the year before. Only species with meaningful value in both years."""
    year = year or int(df["year"].max())
    a = df[df["year"] == year].groupby("species").agg(p=("pounds", "sum"), d=("dollars", "sum"))
    b = df[df["year"] == year - 1].groupby("species").agg(p=("pounds", "sum"), d=("dollars", "sum"))
    j = a.join(b, lsuffix="_now", rsuffix="_prev", how="inner")
    j = j[(j["d_now"] >= min_dollars) & (j["d_prev"] >= min_dollars)]
    j["price_now"], j["price_prev"] = j["d_now"] / j["p_now"], j["d_prev"] / j["p_prev"]
    j["price_chg_pct"] = (j["price_now"] / j["price_prev"] - 1) * 100
    j["pounds_chg_pct"] = (j["p_now"] / j["p_prev"] - 1) * 100
    cols = ["price_prev", "price_now", "price_chg_pct", "pounds_chg_pct", "d_now"]
    j = j[cols].reset_index().rename(columns={"d_now": "dollars"})
    return {"year": year, "up": j.sort_values("price_chg_pct", ascending=False).head(n).reset_index(drop=True),
            "down": j.sort_values("price_chg_pct").head(n).reset_index(drop=True)}


# ---------------------------------------------------------------- states
def state_table(states: pd.DataFrame, species: str, year: int | None = None, region: str | None = None) -> pd.DataFrame:
    d = states[states["species"] == species]
    if region and region != "All regions":
        d = d[d["region"] == region]
    year = year or (int(d["year"].max()) if len(d) else 0)
    d = d[d["year"] == year].copy()
    tot = d["pounds"].sum()
    d["share_pct"] = d["pounds"] / tot * 100 if tot else 0
    out = d.sort_values("pounds", ascending=False)[["state", "region", "pounds", "price", "share_pct"]].reset_index(drop=True)
    out.attrs["year"] = year
    return out


def concentration(tbl: pd.DataFrame) -> dict:
    """How dependent landings are on one state. Plain shares, no jargon."""
    if tbl.empty:
        return {"ok": False}
    top = tbl.iloc[0]
    top3 = float(tbl["share_pct"].head(3).sum())
    label = "highly concentrated" if top["share_pct"] >= 60 else "concentrated" if top["share_pct"] >= 35 else "spread out"
    return {"ok": True, "top_state": top["state"], "top_share_pct": round(float(top["share_pct"]), 1),
            "top3_share_pct": round(top3, 1), "label": label, "n_states": int(len(tbl))}


def state_series(states: pd.DataFrame, species: str, state: str) -> pd.DataFrame:
    d = states[(states["species"] == species) & (states["state"] == state)]
    s = d.groupby("year", as_index=False).agg(pounds=("pounds", "sum"), dollars=("dollars", "sum"))
    s["price"] = s["dollars"] / s["pounds"]
    return s.sort_values("year").reset_index(drop=True)


# ---------------------------------------------------------------- recreational vs commercial
def rec_vs_commercial(loaded: Loaded, species: str, region: str | None = None) -> dict:
    """Pounds caught by recreational anglers (MRIP) against commercial pounds, same species, years in common."""
    rec = loaded.rec
    if rec is None or rec.empty:
        return {"ok": False, "reason": "No recreational data loaded."}
    r = rec[rec["species"] == species]
    c = loaded.df[loaded.df["species"] == species]
    if region and region != "All regions":
        r, c = r[r["region"] == region], c[c["region"] == region]
    r = r.groupby("year", as_index=False).agg(rec_pounds=("pounds", "sum"), rec_fish=("fish", "sum"))
    c = c.groupby("year", as_index=False).agg(comm_pounds=("pounds", "sum"))
    j = r.merge(c, on="year", how="inner")
    j = j[(j["rec_pounds"] > 0) & (j["comm_pounds"] > 0)]
    if len(j) < 3:
        return {"ok": False, "reason": "Fewer than 3 years where both recreational and commercial pounds exist."}
    last = j.iloc[-1]
    share = float(last["rec_pounds"] / (last["rec_pounds"] + last["comm_pounds"]) * 100)
    return {"ok": True, "table": j.reset_index(drop=True), "year": int(last["year"]), "rec_share_pct": round(share, 1),
            "label": "mostly recreational" if share >= 60 else "mostly commercial" if share <= 40 else "mixed",
            "note": "Recreational catch is estimated by NOAA surveys (MRIP), has no price, and covers 1980 onward."}


# ---------------------------------------------------------------- interpretation flags
def interpretation_flags(a: dict) -> list[str]:
    """Plain-language flags from numbers already in analyse(). They suggest, never assert, a cause."""
    out = []
    p, q = a.get("yoy_price_pct"), a.get("yoy_pounds_pct")
    if p is not None and q is not None:
        if p >= 10 and q <= -10:
            out.append("Price rose while landings fell. That pattern often means tighter supply, but this data cannot prove it.")
        elif p <= -10 and q >= 10:
            out.append("Price fell while landings rose. That pattern often means more supply pushing prices down, but this data cannot prove it.")
        elif p >= 10 and q >= 10:
            out.append("Both price and landings rose. Demand or quality may have changed; this data cannot say which.")
        elif abs(p) >= 40:
            out.append("A price move this large in one year is unusual; check the source years and units before relying on it.")
    return out
