"""One function per catalogue entry. Each runs fixed, parameterised pandas logic (a model never writes code or queries)
and returns a ToolResult: claims with dataset, query id, row count and origin, plus caveats and a validation handoff."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import pandas as pd

from .. import crosswalk, live, real_data, validators, wiki
from ..config import DEFAULT
from ..contracts import StageHandoff
from .context import Context
from .origin import REAL, SYNTH_SENTENCE, SYNTHETIC
from . import synthetic

NOAA, GBIF, CPI, FICT, SYN = "NOAA-LANDINGS", "GBIF-OCC", "CPI-U", "FICTIONAL-DEMO", "SYNTH-ANCHORED"
MIN_BIN = 30                 # a GBIF decade/month bin with fewer records is refused
KM_PER_DEG_LAT = 111.0


@dataclass
class Claim:
    id: str
    text: str
    dataset_id: str
    query_id: str
    rows_used: int
    origin: str                       # REAL_NOAA, REAL_GBIF, SYNTHETIC, DERIVED
    inputs_origin: tuple = ()
    number_note: str = ""

    def __post_init__(self):
        if not self.inputs_origin:
            self.inputs_origin = (self.origin,)


@dataclass
class ToolResult:
    entry_id: str
    claims: list[Claim] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    handoff: StageHandoff | None = None
    partial: str = ""                 # set when only part of the question could be answered
    refusal: str = ""                 # set when the tool cannot answer
    data: dict = field(default_factory=dict)
    species: list[str] = field(default_factory=list)
    region: str | None = None
    match_type: str = ""


def _c(tool, n, text, ds, rows, origin="REAL_NOAA", **kw) -> Claim:
    return Claim(f"{tool[:3].upper()}{n}", text, ds, f"{tool}.v1", int(rows), origin, **kw)


def _money(v: float) -> str:
    """Dollar amount in a unit that keeps small numbers readable."""
    if v >= 1e9:
        return f"${v/1e9:,.2f} billion"
    if v >= 1e6:
        return f"${v/1e6:,.1f} million"
    if v >= 1e3:
        return f"${v/1e3:,.0f} thousand"
    return f"${v:,.0f}"


def _usd(x):
    return f"${x:,.2f}"


def _reg(region):
    return "all regions" if not region or region == "All regions" else region


# ------------------------------------------------------------------ NOAA tools
def price_history(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    gate = validators.gate_series(ctx.noaa, sp, region)
    r = ToolResult("price_history", handoff=gate, species=[sp], region=region)
    if gate.status == "FLAGGED":
        r.refusal = f"{gate.flag_reason} {gate.required_action}"
        return r
    a = real_data.analyse(ctx.noaa.df, sp, region)
    s = real_data.series(ctx.noaa.df, sp, region)
    n = len(s)
    r.claims.append(_c("price_history", 1, f"{sp} in {_reg(region)}: the {a['last_year']} dockside price was {_usd(a['latest_price'])} per lb.", NOAA, n))
    if a.get("yoy_price_pct") is not None:
        r.claims.append(_c("price_history", 2, f"That is {a['yoy_price_pct']:+.1f}% compared with {a['last_year'] - 1}, while landings changed {a['yoy_pounds_pct']:+.1f}%.", NOAA, n))
    if a.get("recent_avg_price") is not None:
        r.claims.append(_c("price_history", 3, f"The 5-year average price is {_usd(a['recent_avg_price'])} per lb; the latest year is {a['latest_vs_recent_avg_pct']:+.1f}% against it. "
                                              f"Year-to-year swings are {a['volatility_label']}.", NOAA, n))
    if years:
        lo, hi = years
        w = s[(s["year"] >= lo) & (s["year"] <= hi)]
        if len(w) >= 2:
            p0, p1 = float(w["price"].iloc[0]), float(w["price"].iloc[-1])
            r.claims.append(_c("price_history", 4, f"From {int(w['year'].iloc[0])} to {int(w['year'].iloc[-1])} the price went from {_usd(p0)} to {_usd(p1)} per lb ({(p1 / p0 - 1) * 100:+.1f}%).", NOAA, len(w)))
    r.claims.append(_c("price_history", 5, f"Data runs {a['first_year']} to {a['last_year']} ({a['years_of_data']} years).", NOAA, n))
    r.caveats += a["caveats"] + real_data.interpretation_flags(a)
    r.data = {"series": s, "analysis": a}
    return r


def price_vs_inflation(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    gate = validators.gate_series(ctx.noaa, sp, region)
    r = ToolResult("price_vs_inflation", handoff=gate, species=[sp], region=region)
    if gate.status == "FLAGGED":
        r.refusal = f"{gate.flag_reason} {gate.required_action}"
        return r
    t = real_data.real_trend(ctx.noaa.df, sp, region)
    if not t.get("ok"):
        r.refusal = "Fewer than 5 years of data with a matching inflation index."
        return r
    n = len(t["real_series"])
    r.claims += [
        _c("price_vs_inflation", 1, f"Since {t['first_year']}, the {sp} price rose {t['nominal_cagr_pct']:.1f}% a year as reported, but {t['real_cagr_pct']:.1f}% a year after inflation (in {t['base_year']} dollars).", NOAA, n, inputs_origin=("REAL_NOAA", "REAL_NOAA"), origin="REAL_NOAA"),
        _c("price_vs_inflation", 2, f"Inflation alone was {t['inflation_cagr_pct']:.1f}% a year over the same period.", CPI, n, origin="REAL_OTHER"),
    ]
    verdict = "kept ahead of" if t["real_cagr_pct"] > 0.5 else "fell behind" if t["real_cagr_pct"] < -0.5 else "roughly matched"
    r.claims.append(_c("price_vs_inflation", 3, f"So the price has {verdict} inflation.", NOAA, n, origin="DERIVED", inputs_origin=("REAL_NOAA", "REAL_OTHER")))
    r.caveats += ["Inflation uses US CPI-U (all items), not a seafood-specific index.", "Annual dockside prices only."]
    return r


def landings_trend(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    gate = validators.gate_series(ctx.noaa, sp, region)
    r = ToolResult("landings_trend", handoff=gate, species=[sp], region=region)
    if gate.status == "FLAGGED":
        r.refusal = f"{gate.flag_reason} {gate.required_action}"
        return r
    s = real_data.series(ctx.noaa.df, sp, region)
    last = int(s["year"].iloc[-1])
    cur = float(s["pounds"].iloc[-1])
    r.claims.append(_c("landings_trend", 1, f"{sp} landings in {_reg(region)} were {cur / 1e6:,.2f} million lb in {last}.", NOAA, len(s)))
    b5 = s[s["year"] == last - 5]
    if len(b5):
        ch = (cur / float(b5["pounds"].iloc[0]) - 1) * 100
        r.claims.append(_c("landings_trend", 2, f"That is {ch:+.1f}% compared with {last - 5}.", NOAA, len(s)))
    b10 = s[s["year"] == last - 10]
    if len(b10) and float(b10["pounds"].iloc[0]) > 0:
        cagr = ((cur / float(b10["pounds"].iloc[0])) ** (1 / 10) - 1) * 100
        r.claims.append(_c("landings_trend", 3, f"Over the last 10 years landings changed {cagr:+.1f}% a year.", NOAA, len(s)))
    pk = s.loc[s["pounds"].idxmax()]
    r.claims.append(_c("landings_trend", 4, f"The record year was {int(pk['year'])} with {float(pk['pounds']) / 1e6:,.2f} million lb; {last} is {cur / float(pk['pounds']) * 100:.0f}% of that.", NOAA, len(s)))
    r.caveats += ["Annual commercial landings in pounds; reflects fishing effort and regulations as well as fish numbers."]
    r.data = {"series": s}
    return r


def best_region_price(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    gate = validators.gate_series(ctx.noaa, sp, None)
    r = ToolResult("best_region_price", handoff=gate, species=[sp])
    if gate.status == "FLAGGED":
        r.refusal = f"{gate.flag_reason} {gate.required_action}"
        return r
    a = real_data.analyse(ctx.noaa.df, sp, None)
    rows = a.get("regions_latest_year") or []
    if len(rows) < 2:
        r.refusal = f"{sp} has dockside data in fewer than two regions in {a['last_year']}."
        return r
    top = rows[:3]
    txt = "; ".join(f"{x['region']} {_usd(x['price'])}" for x in top)
    r.claims.append(_c("best_region_price", 1, f"In {a['last_year']}, {sp} dockside prices were highest in: {txt} per lb.", NOAA, len(rows)))
    lo = rows[-1]
    r.claims.append(_c("best_region_price", 2, f"The lowest was {lo['region']} at {_usd(lo['price'])} per lb.", NOAA, len(rows)))
    r.caveats += ["Regions with under 1% of the species' landings are left out.", "Dockside price differences can reflect size, product form and market level."]
    r.data = {"regions": rows}
    return r


def concentration(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    gate = validators.gate_series(ctx.noaa, sp, region)
    r = ToolResult("concentration", handoff=gate, species=[sp], region=region)
    if gate.status == "FLAGGED":
        r.refusal = f"{gate.flag_reason} {gate.required_action}"
        return r
    tb = real_data.state_table(ctx.noaa.states, sp, region=region)
    c = real_data.concentration(tb)
    if not c["ok"]:
        r.refusal = "No state-level landings found."
        return r
    yr = tb.attrs.get("year")
    r.claims.append(_c("concentration", 1, f"{sp} landings are {c['label']}: {c['top_state']} supplies {c['top_share_pct']:.1f}% of {yr} pounds.", NOAA, len(tb)))
    r.claims.append(_c("concentration", 2, f"The top 3 states supply {c['top3_share_pct']:.1f}% across {c['n_states']} states with landings.", NOAA, len(tb)))
    r.caveats += ["State of landing, not where the fish were caught."]
    r.data = {"table": tb}
    return r


def rec_vs_commercial(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    r = ToolResult("rec_vs_commercial", species=[sp], region=region)
    x = real_data.rec_vs_commercial(ctx.noaa, sp, region)
    if not x["ok"]:
        r.refusal = x["reason"]
        return r
    t = x["table"]
    last = t.iloc[-1]
    r.claims.append(_c("rec_vs_commercial", 1, f"In {x['year']}, anglers caught {x['rec_share_pct']:.1f}% of the combined recreational and commercial pounds of {sp} ({x['label']}).", NOAA, len(t)))
    r.claims.append(_c("rec_vs_commercial", 2, f"Recreational catch was {last['rec_pounds'] / 1e6:,.2f} million lb and commercial landings {last['comm_pounds'] / 1e6:,.2f} million lb.", NOAA, len(t)))
    r.caveats += [x["note"]]
    return r


def biggest_movers(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    m = real_data.movers(ctx.noaa.df)
    r = ToolResult("biggest_movers")
    if m["up"].empty:
        r.refusal = "No species meet the minimum landed value in both years."
        return r
    up, dn = m["up"].head(3), m["down"].head(3)
    y = m["year"]
    r.claims.append(_c("biggest_movers", 1, "Biggest dockside price rises in {y} vs {p}: ".format(y=y, p=y - 1) + "; ".join(f"{x.species} {x.price_chg_pct:+.1f}%" for x in up.itertuples()) + ".", NOAA, len(m["up"])))
    r.claims.append(_c("biggest_movers", 2, "Biggest falls: " + "; ".join(f"{x.species} {x.price_chg_pct:+.1f}%" for x in dn.itertuples()) + ".", NOAA, len(m["down"])))
    r.caveats += ["Only species with at least 5 million dollars of landed value in both years.", "Large moves often follow large changes in landings; this data cannot say why."]
    r.data = m
    return r


def compare_species(ctx: Context, species: list[str], region=None, years=None, question: str = "") -> ToolResult:
    """Compares 2 to 6 species by price, or by landings when the question asks about landings, in the latest year every
    species has data, so the years always match."""
    by_pounds = bool(re.search(r"\b(landings|landed|land|catch|caught|pounds|volume|tonnage|harvest)\b", question, re.I)) and \
        not re.search(r"\b(price|prices|cost|worth|expensive|cheaper)\b", question, re.I)
    sps = list(dict.fromkeys(species))[:6]
    r = ToolResult("compare_species", species=sps, region=region)
    if len(sps) < 2:
        r.refusal = "I need at least two species to compare."
        return r
    out, skipped, handoffs = [], [], []
    for sp in sps:
        g = validators.gate_series(ctx.noaa, sp, region)
        handoffs.append(g)
        a = real_data.analyse(ctx.noaa.df, sp, region)
        if g.status == "FLAGGED" or not a.get("ok"):
            skipped.append(f"{sp} ({g.flag_reason or 'no usable price data'})")
            continue
        out.append((sp, a))
    if len(out) < 2:
        r.refusal = "Not enough usable data to compare: " + "; ".join(skipped)
        return r
    r.handoff = next((h for h in handoffs if h.status != "OK"), handoffs[0])
    df = ctx.noaa.df[ctx.noaa.df["species"].isin([sp for sp, _ in out])]
    if region:
        df = df[df["region"] == region]
    df = df[(df["pounds"] > 0) & (df["dollars"] > 0)]
    yrs = df.groupby("species")["year"].apply(set)
    common = set.intersection(*yrs.tolist()) if len(yrs) == len(out) else set()
    where = f" in {region}" if region else ""
    if common:
        y = max(common)
        g = df[df["year"] == y].groupby("species")[["dollars", "pounds"]].sum()
        if by_pounds:
            lbs = g["pounds"].sort_values(ascending=False)
            txt = "; ".join(f"{sp} {v / 1e6:,.1f} million lb" for sp, v in lbs.items())
            r.claims.append(_c("compare_species", 1, f"Commercial landings{where} in {y}, the latest year all {len(lbs)} species have data: {txt}.", NOAA, int(len(df[df['year'] == y]))))
            if lbs.iloc[-1] > 0:
                r.claims.append(_c("compare_species", 2, f"{lbs.index[0]} landings are {lbs.iloc[0] / lbs.iloc[-1]:,.1f} times those of {lbs.index[-1]} in {y}.", NOAA, 2))
        else:
            prices = (g["dollars"] / g["pounds"]).sort_values(ascending=False)
            txt = "; ".join(f"{sp} {_usd(v)}" for sp, v in prices.items())
            r.claims.append(_c("compare_species", 1, f"Dockside prices per lb{where} in {y}, the latest year all {len(prices)} species have data: {txt}.", NOAA, int(len(df[df['year'] == y]))))
            if prices.iloc[-1] > 0:
                r.claims.append(_c("compare_species", 2, f"{prices.index[0]} is {prices.iloc[0] / prices.iloc[-1]:.1f} times the price of {prices.index[-1]} in {y}.", NOAA, 2))
        late = [(sp, a) for sp, a in out if a["last_year"] > y]
        if late:
            r.caveats.append("Some species have later data than " + str(y) + ": " + ", ".join(f"{sp} {_usd(a['latest_price'])} in {a['last_year']}" for sp, a in late) + ". Those are not compared with older years.")
    else:
        txt = "; ".join(f"{sp} {_usd(a['latest_price'])} in {a['last_year']}" for sp, a in out)
        r.claims.append(_c("compare_species", 1, f"These species have no year of data in common{where}, so they are listed separately rather than compared: {txt}.", NOAA, sum(a['years_of_data'] for _, a in out)))
    for k, (sp, x) in enumerate(out, 3):
        if x.get("recent_trend_pct_per_year") is not None and not by_pounds:
            r.claims.append(_c("compare_species", k, f"{sp}: 5-year trend {x['recent_trend_pct_per_year']:+.1f}% a year ({x['trend_direction']}).", NOAA, x["years_of_data"]))
    if skipped:
        r.partial = "Left out for lack of usable data: " + "; ".join(skipped) + "."
    r.caveats += (["Commercial landings by weight; species differ a lot in size and value, so pounds alone do not show importance."] if by_pounds else
                  ["Different species are often sold in different product forms; dockside price per pound is not a like-for-like quality comparison."])
    return r


def data_quality(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    gate = validators.gate_series(ctx.noaa, sp, region)
    r = ToolResult("data_quality", handoff=gate, species=[sp], region=region)
    rs = gate.payload.get("row_status", {})
    tot = sum(rs.values())
    if not tot:
        r.refusal = f"No NOAA rows found for {sp}."
        return r
    r.claims.append(_c("data_quality", 1, f"NOAA has {tot:,} rows for {sp}: {rs.get('VALID', 0):,} valid, {rs.get('REVIEW', 0):,} held for review, {rs.get('REJECTED', 0):,} rejected, {rs.get('EXCLUDED_BY_DESIGN', 0):,} not errors by design.", NOAA, tot))
    r.claims.append(_c("data_quality", 2, f"The validation gate result is {gate.status}" + (f": {gate.flag_reason}" if gate.flag_reason else "."), NOAA, tot))
    if gate.payload.get("gaps"):
        r.claims.append(_c("data_quality", 3, f"Missing years in the valid series: {', '.join(map(str, gate.payload['gaps'][:6]))}.", NOAA, tot))
    r.caveats += ["Rows are excluded, never silently changed."]
    return r


# ------------------------------------------------------------------ GBIF tools
def _taxa(ctx: Context, sp: str):
    if ctx.cw is None:
        return [], "none"
    return crosswalk.taxon_keys(ctx.cw, sp)


def _gbif_gate_note(ctx: Context, r: ToolResult) -> None:
    rep = ctx.gold.report
    if rep:
        r.caveats.append(f"GBIF rows passed the validation gate: {rep.get('valid_rows', 0):,} of {rep.get('total_rows', 0):,} ({rep.get('pass_rate', 0):.1%}).")
    r.caveats.append("GBIF records show where and when people recorded the species, not how many exist.")
    if ctx.gold.manifest.get("is_test_fixture"):
        r.caveats.append("TEST FIXTURE: this GBIF data is synthetic test data, not real GBIF records.")
    if ctx.gold.manifest.get("source_kind") == "api_sample":
        r.partial = r.partial or ("The GBIF data here is a sample of up to a few hundred records per species from GBIF's search API, "
                                  "not a complete download, so counts, ranges and trends are indicative only.")


def _gbif_origin(ctx: Context) -> str:
    return "TEST_FIXTURE" if ctx.gold.manifest.get("is_test_fixture") else "REAL_GBIF"


def _need_taxa(ctx, sp, entry):
    keys, mt = _taxa(ctx, sp)
    r = ToolResult(entry, species=[sp], match_type=mt)
    if not keys:
        why = {"group": "NOAA lists it as a group (family or mixed category), so there is no species-level GBIF link.",
               "none": "its scientific name does not match any species in the loaded GBIF data."}.get(mt, "no GBIF match.")
        r.refusal = f"I can't link {sp} to GBIF: {why}"
    elif mt == "genus_level":
        r.partial = f"{sp} is linked to GBIF only at genus level, so this covers every species of that genus in the data."
    return r, keys


def where_found(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    r, keys = _need_taxa(ctx, sp, "where_found")
    if r.refusal:
        return r
    y = ctx.gold.year[ctx.gold.year["taxon"].isin(keys)]
    org = _gbif_origin(ctx)
    tot = int(y["n"].sum())
    byr = y.groupby("region")["n"].sum().sort_values(ascending=False)
    top = ", ".join(f"{k} ({int(v):,})" for k, v in byr.head(3).items())
    r.claims.append(_c("where_found", 1, f"GBIF has {tot:,} valid records of {sp}. The most records are in: {top}.", GBIF, len(y), org))
    r.claims.append(_c("where_found", 2, f"Records span latitudes {y['lat_min'].min():.1f} to {y['lat_max'].max():.1f} and years {int(y['year_i'].min())} to {int(y['year_i'].max())}.", GBIF, len(y), org))
    r.data = {"by_region": byr, "points": ctx.gold.points[ctx.gold.points["taxon"].isin(keys)]}
    _gbif_gate_note(ctx, r)
    return r


def range_shift(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    r, keys = _need_taxa(ctx, sp, "range_shift")
    if r.refusal:
        return r
    y = ctx.gold.year[ctx.gold.year["taxon"].isin(keys)].copy()
    y["decade"] = (y["year_i"] // 10 * 10).astype(int)
    d = y.groupby("decade").agg(n=("n", "sum"), lat_sum=("lat_sum", "sum")).reset_index()
    d["lat"] = d["lat_sum"] / d["n"]
    d = d[d["n"] >= MIN_BIN]
    org = _gbif_origin(ctx)
    if len(d) < 2:
        r.refusal = f"Fewer than two decades have at least {MIN_BIN} valid records for {sp}, so a shift can't be judged."
        return r
    a, b = d.iloc[0], d.iloc[-1]
    dlat = b["lat"] - a["lat"]
    direction = "north" if dlat > 0.1 else "south" if dlat < -0.1 else "no clear direction"
    r.claims.append(_c("range_shift", 1, f"The average latitude of {sp} records moved from {a['lat']:.2f} in the {int(a['decade'])}s to {b['lat']:.2f} in the {int(b['decade'])}s, a change of {dlat:+.2f} degrees ({direction}).", GBIF, len(y), org))
    r.claims.append(_c("range_shift", 2, f"That is about {abs(dlat) * KM_PER_DEG_LAT:,.0f} km. The {int(a['decade'])}s have {int(a['n']):,} records and the {int(b['decade'])}s have {int(b['n']):,}.", GBIF, len(y), org))
    ratio = b["n"] / a["n"]
    if ratio > 1.5 or ratio < 0.67:
        r.caveats.append(f"The number of records changed by a factor of {ratio:.1f} between those decades, so observer effort changed; treat the shift as a hint, not proof.")
    r.data = {"decades": d}
    _gbif_gate_note(ctx, r)
    return r


def seasonal_presence(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    r, keys = _need_taxa(ctx, sp, "seasonal_presence")
    if r.refusal:
        return r
    m = ctx.gold.month[ctx.gold.month["taxon"].isin(keys)]
    if region and region != "All regions":
        m = m[m["region"] == region]
    h = m.groupby("month_i")["n"].sum()
    tot = int(h.sum())
    if tot < MIN_BIN:
        r.refusal = f"Only {tot} valid records with a month for {sp}{' in ' + region if region else ''}; at least {MIN_BIN} are needed."
        return r
    org = _gbif_origin(ctx)
    names = synthetic.MONTHS
    top = h.sort_values(ascending=False).head(3)
    share = float(top.sum() / tot * 100)
    top_months = ", ".join(names[int(k) - 1] for k in sorted(top.index))
    r.claims.append(_c("seasonal_presence", 1, f"{sp} records{' in ' + region if region else ''} are most often in {top_months} ({share:.0f}% of {tot:,} records with a month).", GBIF, len(m), org))
    low = h[h < 0.02 * tot]
    quiet = [names[k - 1] for k in range(1, 13) if k not in h.index or h.get(k, 0) < 0.02 * tot]
    if quiet:
        r.claims.append(_c("seasonal_presence", 2, f"Almost no records in {', '.join(quiet)}.", GBIF, len(m), org))
    r.data = {"hist": h}
    _gbif_gate_note(ctx, r)
    r.caveats.append("This is when people recorded it, not when it is abundant or when it can be fished.")
    return r


def species_background(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    r, keys = _need_taxa(ctx, sp, "species_background")
    if r.refusal:
        return r
    t = ctx.gold.taxa[ctx.gold.taxa["taxon"].isin(keys)]
    row = t.sort_values("n_valid", ascending=False).iloc[0]
    org = _gbif_origin(ctx)
    r.claims.append(_c("species_background", 1, f"{sp} is {row['scientific_name']} in the family {row['family']}.", GBIF, len(t), org))
    r.claims.append(_c("species_background", 2, f"The loaded GBIF data has {int(t['n_valid'].sum()):,} valid records for it.", GBIF, len(t), org))
    _gbif_gate_note(ctx, r)
    return r


def landings_vs_sightings(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    r, keys = _need_taxa(ctx, sp, "landings_vs_sightings")
    if r.refusal:
        return r
    df = ctx.noaa.df
    last = int(df["year"].max())
    nl = df[(df["species"] == sp) & (df["year"] > last - 5)].groupby("region")["pounds"].sum()
    gy = ctx.gold.year[ctx.gold.year["taxon"].isin(keys)]
    gy = gy[gy["year_i"] > gy["year_i"].max() - 10].groupby("region")["n"].sum()
    gy = gy[gy.index != "Outside NOAA regions"]
    both = pd.DataFrame({"landings": nl, "records": gy}).fillna(0)
    if both["landings"].sum() <= 0 or both["records"].sum() < MIN_BIN:
        r.refusal = "Not enough landings or records in NOAA regions to compare."
        return r
    both["l_share"], both["r_share"] = both["landings"] / both["landings"].sum() * 100, both["records"] / both["records"].sum() * 100
    top = both.sort_values("l_share", ascending=False).head(3)
    org = _gbif_origin(ctx)
    txt = "; ".join(f"{i}: {x.l_share:.0f}% of landings, {x.r_share:.0f}% of records" for i, x in top.iterrows())
    r.claims.append(_c("landings_vs_sightings", 1, f"For {sp}, by region ({txt}).", GBIF, len(both), org, inputs_origin=("REAL_NOAA", "REAL_NOAA")))
    r.caveats += ["Descriptive only: landings reflect fishing effort, rules and markets; records reflect observers. Neither explains the other.",
                  "Regions are approximate lat/lon boxes, not official boundaries."]
    _gbif_gate_note(ctx, r)
    r.data = {"table": both}
    return r


def recent_sightings_in_region(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    r = ToolResult("recent_sightings_in_region", region=region)
    if not region or region == "All regions":
        r.refusal = "Tell me which region (for example Gulf or New England)."
        return r
    y = ctx.gold.year
    yr = years[1] if years and years[0] == years[1] else None
    sel = y[(y["region"] == region)]
    if years:
        sel = sel[(sel["year_i"] >= years[0]) & (sel["year_i"] <= years[1])]
    g = sel.groupby("taxon")["n"].sum().sort_values(ascending=False).head(5)
    if g.empty:
        r.refusal = f"No valid GBIF records in {region}" + (f" for {years[0]}-{years[1]}." if years else ".")
        return r
    taxa = ctx.gold.taxa.set_index("taxon")
    org = _gbif_origin(ctx)
    txt = "; ".join(f"{taxa.loc[k, 'species']} ({int(v):,})" for k, v in g.items())
    when = f" in {years[0]}" if years and years[0] == years[1] else f" in {years[0]}-{years[1]}" if years else ""
    r.claims.append(_c("recent_sightings_in_region", 1, f"Most-recorded species in {region}{when}: {txt} records.", GBIF, len(sel), org))
    r.caveats += ["Regions are approximate lat/lon boxes.", "Only taxa present in the loaded GBIF data are counted."]
    _gbif_gate_note(ctx, r)
    return r


# ------------------------------------------------------------------ fallback tools (rungs 3 and 4)
def _stale(ctx: Context, a: dict) -> str:
    """Why a generated filler must not be scaled to this species, or an empty string."""
    last = int(ctx.noaa.df["year"].max())
    if a.get("last_year", last) < last - 5:
        return f"NOAA has no landings of this species since {a['last_year']}, so there is no recent level to scale a generated example to."
    if a.get("latest_price", 0) * a.get("latest_pounds", 0) < 1e6:
        return "NOAA landings of this species are too small (under $1 million a year) to scale a sensible generated example to."
    return ""


def monthly_timing(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    r = ToolResult("monthly_timing", species=[sp], region=region)
    a = real_data.analyse(ctx.noaa.df, sp, region)
    if not a.get("ok"):
        r.refusal = "No annual NOAA price to anchor a generated pattern to."
        return r
    if _stale(ctx, a):
        r.refusal = _stale(ctx, a)
        return r
    prof = synthetic.monthly_profile(sp, region or "All regions", a["latest_price"], a["latest_pounds"])
    best = synthetic.best_months(prof)
    txt = ", ".join(f"{m} ({_usd(p)})" for m, p in best)
    r.claims.append(_c("monthly_timing", 1, f"In the generated pattern for {sp}, the highest-priced months are {txt} per lb. {SYNTH_SENTENCE}", SYN, 12, "SYNTHETIC", number_note="seed " + str(prof["seed"])))
    r.caveats += ["NOAA has no monthly prices. This pattern is generated (seeded, repeatable) around the real " + str(a["last_year"]) + " annual price and says nothing real about months."]
    r.data = {"profile": prof}
    return r


def market_compare(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    from ..loader import load_dataset
    sp = species[0]
    r = ToolResult("market_compare", species=[sp], region=region)
    mp = load_dataset(DEFAULT, "market_prices")
    mp = mp[mp["species"].str.lower() == sp.lower()]
    if mp.empty:
        r.refusal = f"The fictional demo dataset has no market prices for {sp}, and NOAA and GBIF have none."
        return r
    last = mp["date"].max()
    cur = mp[mp["date"] == last].copy()
    cur["price"] = pd.to_numeric(cur["price"], errors="coerce")
    mk = load_dataset(DEFAULT, "markets").set_index("market_id")["name"].to_dict()
    top = cur.groupby("market_id")["price"].mean().sort_values(ascending=False).head(3)
    txt = "; ".join(f"{mk.get(k, k)} {_usd(v)}" for k, v in top.items())
    r.claims.append(_c("market_compare", 1, f"In the fictional demo data for {last}, the highest {sp} market prices were: {txt} per lb. This is fictional demo data, not a real market.", FICT, len(cur), "SYNTHETIC"))
    r.caveats += ["Fictional, seeded demo dataset. NOAA and GBIF contain no market prices."]
    return r


CRUSTACEAN = ("lobster", "crab", "shrimp", "prawn", "crawfish", "crayfish", "krill")
MOLLUSC = ("scallop", "oyster", "clam", "mussel", "squid", "abalone", "conch", "octopus", "whelk", "cockle")


def _hs_for(sp: str | None) -> list[str]:
    n = (sp or "").lower()
    if any(w in n for w in CRUSTACEAN):
        return ["0306"]
    if any(w in n for w in MOLLUSC):
        return ["0307"]
    if n:
        return ["0302", "0303", "0304"]
    return list(live.HS4)


def obis_profile(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    sp = species[0]
    r = ToolResult("obis_profile", species=[sp])
    if not ctx.live:
        r.refusal = "Live OBIS lookups are switched off. Set FISHMARKET_LIVE=1 (or start with --live) to allow small free API calls to OBIS."
        return r
    sci = ctx.noaa.df.loc[ctx.noaa.df["species"] == sp, "scientific"].dropna().astype(str)
    if sci.empty:
        r.refusal = f"No scientific name for {sp} in the NOAA file, so OBIS can't be searched."
        return r
    name = sci.iloc[0]
    try:
        p = live.obis_profile(name, int(ctx.noaa.df["year"].max()), fetch=ctx.live_fetch)
    except live.LiveError as e:
        r.refusal = f"OBIS could not be reached or answered unexpectedly ({e}). Nothing was guessed."
        return r
    if p["total"] == 0:
        r.refusal = f"OBIS has no records under the name {name}."
        return r
    dec = ", ".join(f"{d}s: {n:,}" for d, n in p["by_decade"].items())
    r.claims.append(_c("obis_profile", 1, f"OBIS holds {p['total']:,} occurrence records for {name} ({sp}). Records by decade: {dec}.", "OBIS-OCC", p["total"], "REAL_OTHER"))
    if "lat_range" in p:
        r.claims.append(_c("obis_profile", 2, f"In a sample of {p['sample_points']:,} recent OBIS records, the middle 90% lie between latitude {p['lat_range'][0]:.1f} and {p['lat_range'][1]:.1f}.", "OBIS-OCC", p["sample_points"], "REAL_OTHER"))
    r.caveats += ["OBIS counts reflect where and when people surveyed, not abundance.", "The latitude range comes from one small sample of recent records, not all of OBIS."]
    r.data = {"profile": p}
    return r


def seafood_trade(ctx: Context, species: list[str], region=None, years=None, question: str = "") -> ToolResult:
    sp = species[0] if species else None
    r = ToolResult("seafood_trade", species=species)
    flow = "exports" if re.search(r"\b(export|exports|exported|exporting|sell abroad)\b", question, re.I) else "imports"
    year = int(ctx.noaa.df["year"].max())
    heads = _hs_for(sp)
    err = ""
    if ctx.live:
        got = []
        try:
            for h in heads:
                for y in (year, year - 1):
                    try:
                        got.append(live.trade_by_country(flow, h, y, fetch=ctx.live_fetch))
                        break
                    except live.LiveError as e:
                        if "no partner rows" not in str(e):
                            raise
                        err = str(e)
        except live.LiveError as e:
            err, got = str(e), []
        for i, g in enumerate(got, 1):
            top = "; ".join(f"{n} ${v/1e6:,.0f} million" for n, v in g["top"][:3])
            r.claims.append(_c("seafood_trade", i, f"In {g['year']}, U.S. {flow} of {g['label']} (HS {g['hs4']}) were ${g['total_usd']/1e9:,.2f} billion across {g['n_partners']} partner countries. Largest partners: {top}.", "CENSUS-TRADE", g["n_partners"], "REAL_OTHER"))
        if r.claims:
            r.caveats += ["Trade is by product heading, not by species: " + ", ".join(f"HS {g['hs4']} = {g['label']}" for g in got) + ".", "Values are U.S. customs value in dollars from the Census Bureau, not retail prices."]
            return r
    hits = wiki.search(question, species, k=1)
    if hits and not sp:
        _, e = hits[0]
        r.claims.append(Claim("TRD1", f"{e.title}: {e.text}", f"WIKI:{e.id}", "seafood_trade.v1", 1, "REAL_OTHER"))
        r.caveats.append("Live Census trade lookups are " + ("unavailable right now" if ctx.live else "switched off") + (f" ({err})" if err else "") + "; this is a sourced background note instead of current figures.")
        return r
    if ctx.real_only or not ctx.allow_synthetic:
        r.refusal = ("Trade figures need a live Census lookup (set FISHMARKET_LIVE=1 and CENSUS_API_KEY)" + (f"; it failed: {err}" if err else "") + ", and real-only mode forbids generated stand-ins.")
        return r
    a = real_data.analyse(ctx.noaa.df, sp, None) if sp else {}
    if not a.get("ok"):
        r.refusal = "No NOAA landed value to scale an illustrative trade figure, and live trade lookups are unavailable."
        return r
    if _stale(ctx, a):
        r.refusal = _stale(ctx, a) + " Live Census lookups (FISHMARKET_LIVE=1) would give real figures."
        return r
    prof = synthetic.trade_profile(sp, flow, a["latest_price"] * a["latest_pounds"])
    top = "; ".join(f"{n} {_money(v)}" for n, v in prof["partners"])
    r.claims.append(_c("seafood_trade", 1, f"In the generated pattern, U.S. {flow} related to {sp} are about {_money(prof['total_usd'])} a year, split {top}. {SYNTH_SENTENCE}", SYN, 3, "SYNTHETIC", number_note="seed " + str(prof["seed"])))
    r.caveats += ["Live Census trade data was unavailable, so this is an invented illustration with placeholder country names. It says nothing real about trade."]
    return r


def _countries(question: str) -> list[tuple[str, str]]:
    """Every country named in the question, in the order written (U.S. when none is named)."""
    ql = " " + question.lower() + " "
    found, taken = [], []
    for name in sorted(live.COUNTRIES, key=len, reverse=True):
        for m in re.finditer(r"(?<![a-z.])" + re.escape(name) + r"(?![a-z])", ql):
            if any(a <= m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            code = live.COUNTRIES[name]
            found.append((m.start(), code, "the U.S." if code == "USA" else ("the U.K." if code == "GBR" else name.title())))
    out, seen = [], set()
    for _, code, nm in sorted(found):
        if code not in seen:
            seen.add(code)
            out.append((code, nm))
    return out or [("USA", "the U.S.")]


def _country(question: str) -> tuple[str, str]:
    return _countries(question)[0]


def _sci(ctx: Context, sp: str) -> str:
    s = ctx.noaa.df.loc[ctx.noaa.df["species"] == sp, "scientific"].dropna().astype(str)
    return s.iloc[0] if not s.empty else ""


def aquaculture_production(ctx: Context, species: list[str], region=None, years=None, question: str = "") -> ToolResult:
    sp = species[0]
    r = ToolResult("aquaculture_production", species=[sp])
    if not (live.farming_available()["oecd"] or ctx.live or ctx.live_fetch):
        r.refusal = "The OECD aquaculture file isn't downloaded yet. Run `python scripts/download_farming_data.py` once (or set FISHMARKET_LIVE=1)."
        return r
    sci = _sci(ctx, sp)
    n = 0
    a_last, ranks = None, []
    for code, cname in _countries(question)[:4]:
        try:
            a = live.aquaculture(sci, code, fetch=ctx.live_fetch)
        except live.LiveError as e:
            r.refusal = f"The OECD Data Explorer could not be reached or answered unexpectedly ({e}). Nothing was guessed."
            return r
        if a["match"] == "none":
            r.caveats.append(f"OECD reports no farmed production of {sp} for {cname}.")
            continue
        a_last = a
        if a.get("rank"):
            ranks.append(f"{cname[0].upper() + cname[1:]} ranks {a['rank']} of {a['n_countries']}")
        ser = a["series"].get("T") or next(iter(a["series"].values()))
        unit = "tonnes" if "T" in a["series"] else a["units"].get(next(iter(a["series"])), "units").lower()
        ys = sorted(ser)
        last, first = ys[-1], ys[0]
        txt = f"OECD reports {cname} farmed production of {a['species_label']} at {ser[last]:,.0f} {unit} in {last}"
        if len(ys) >= 2 and ser[first] > 0:
            txt += f", compared with {ser[first]:,.0f} in {first} ({(ser[last] / ser[first] - 1) * 100:+.0f}%)"
        gf = a.get("gate_flags", {}).get(f"T:{last}", [])
        notes = []
        if "IMPUTED" in gf or ("T", last) in set(map(tuple, a.get("imputed", []))):
            notes.append(f"the {last} figure is marked as imputed by a receiving agency")
        if "CARRIED_FORWARD" in gf or (not a.get("cleaned") and last - 1 in ser and ser[last] == ser[last - 1] and ser[last] > 0):
            notes.append(f"the {last} figure is identical to {last - 1}, which often means it was carried forward rather than newly reported")
        if "JUMP_10X" in gf:
            notes.append(f"the {last} figure changed more than tenfold from the year before, so treat it with caution")
        if notes:
            txt += "; " + "; ".join(notes)
        n += 1
        r.claims.append(_c("aquaculture_production", n, txt + ".", "OECD-AQUA", len(ser), "REAL_OTHER"))
        val = a["series"].get("USD", {})
        if "PRICE_OUTLIER" in gf:
            r.caveats.append(f"OECD's {last} value for {cname} works out to an implausible price per kg, so no value per lb is shown.")
        elif last in val and "T" in a["series"] and ser.get(last):
            per_lb = val[last] / (ser[last] * 2204.62)
            n += 1
            r.claims.append(_c("aquaculture_production", n, f"OECD values {cname}'s {last} production at {_money(val[last])}, about {_usd(per_lb)} per lb live weight (value divided by tonnes).", "OECD-AQUA", 2, "REAL_OTHER"))
        if a.get("dropped_invalid"):
            r.caveats.append(f"{a['dropped_invalid']} OECD value(s) for {cname} were negative or unreadable and were left out.")
    if a_last is None:
        r.refusal = f"OECD reports no farmed production of {sp} ({sci or 'no scientific name'}) for the countries asked about."
        return r
    a = a_last
    if a.get("top_countries"):
        top = "; ".join(f"{nm} {v:,.0f}" for nm, v in a["top_countries"])
        n += 1
        r.claims.append(_c("aquaculture_production", n, f"Largest producers of this species in {a['rank_year']} among countries OECD reports (tonnes): {top}." + (" " + "; ".join(ranks) + "." if ranks else ""), "OECD-AQUA", a["n_countries"], "REAL_OTHER"))
    if a["match"] == "genus":
        r.partial = f"OECD has no exact match for {sci}; this is the closest species in the same genus."
    if a.get("cleaned"):
        r.caveats.append("OECD rows passed the app's cleansing gate; values it flagged are noted in the answer.")
    r.caveats += ["Farmed production by country from the OECD Data Explorer; NOAA landings (wild catch) are a separate measure and are not combined with it.",
                  "OECD covers its member and partner countries, not every producer worldwide."]
    r.data = {"oecd": a}
    return r


def farming_profile(ctx: Context, species: list[str], region=None, years=None, question: str = "") -> ToolResult:
    sp = species[0]
    r = ToolResult("farming_profile", species=[sp])
    if not (live.farming_available()["fishwatch"] or ctx.live_fetch):
        # The FishWatch API has been retired (it now redirects to a NOAA web page), so farming answers come from sourced wiki notes.
        hits = [(sc, e) for sc, e in wiki.search(question or f"how is {sp} farmed", species, k=3) if e.type == "farming"]
        if not hits:
            r.refusal = f"No sourced farming notes for {sp} yet. NOAA's FishWatch API has been retired, so only the farming entries in the mini-wiki are available."
            return r
        top = hits[0][0]
        for i, (sc, e) in enumerate([h for j, h in enumerate(hits) if j == 0 or h[0] >= max(6, top / 2)][:2], 1):
            r.claims.append(Claim(f"FRM{i}", f"{e.title}: {e.text}", f"WIKI:{e.id}", "farming_profile.v2", 1, "REAL_OTHER"))
        r.caveats.append("Background notes from NOAA pages, read on " + ", ".join(sorted({e.retrieved for _, e in hits})) + "; check the source link for the latest.")
        return r
    try:
        rec = live.fishwatch_farmed(sp, _sci(ctx, sp), fetch=ctx.live_fetch)
    except live.LiveError as e:
        r.refusal = f"NOAA FishWatch could not be reached or answered unexpectedly ({e}). Nothing was guessed."
        return r
    if not rec:
        r.refusal = f"FishWatch has no profile for {sp}."
        return r
    q = question.lower()
    order = (["Feeds"] if re.search(r"\b(eat|eats|feed|feeds|fed|diet)\b", q) else []) + \
            (["Disease Treatment and Prevention"] if re.search(r"\b(disease|diseases|health|healthy|sick|parasite|lice)\b", q) else []) + \
            (["Environmental Effects"] if re.search(r"\b(environment|environmental|impact|impacts|pollution|escape)\b", q) else []) + \
            ["Farming Methods", "Production", "Location"]
    picked = [f for f in dict.fromkeys(order) if rec.get(f)][:2]
    if not picked:
        r.refusal = f"The FishWatch profile for {rec['name']} has no farming information" + (f" (harvest type: {rec['Harvest Type']})." if rec.get("Harvest Type") else ".")
        return r
    for i, f in enumerate(picked, 1):
        words = rec[f].split()
        text = " ".join(words[:90]) + (" ..." if len(words) > 90 else "")
        r.claims.append(_c("farming_profile", i, f"{rec['name']} ({f.lower()}, NOAA FishWatch): {text}", "FISHWATCH", 1, "REAL_OTHER"))
    if "farm" not in (rec.get("Harvest Type", "") + rec["name"]).lower():
        r.partial = f"FishWatch lists this species as {rec.get('Harvest Type') or 'not farmed'}, so there may be no farming detail."
    r.caveats.append("Quoted from NOAA FishWatch" + (f" (profile updated {rec['updated']})" if rec.get("updated") else "") + "; profiles can be several years old.")
    return r


def cost_profile(ctx: Context, species: list[str], region=None, years=None) -> ToolResult:
    r = ToolResult("cost_profile", species=species)
    if ctx.real_only or not ctx.allow_synthetic:
        r.refusal = "NOAA and GBIF have no cost, margin or storage data, and real-only mode forbids generated or fictional stand-ins."
        return r
    sp = species[0] if species else None
    if not sp:                                 # an example species with a sensible dockside price (at least $1 per lb)
        for cand in ctx.species:
            an = real_data.analyse(ctx.noaa.df, cand, region)
            if an.get("ok") and an["latest_price"] >= 1.0 and an["latest_pounds"] > 1e6:
                sp = cand
                break
    a = real_data.analyse(ctx.noaa.df, sp, region) if sp else {}
    if sp and not species:
        r.caveats.append(f"You didn't name a species, so {sp} (the biggest by landed value) is the example.")
    if not a.get("ok"):
        r.refusal = "No NOAA annual price to scale a fictional cost profile to."
        return r
    if _stale(ctx, a):
        r.refusal = _stale(ctx, a)
        return r
    p = synthetic.cost_profile(sp, a["latest_price"])
    parts = ", ".join(f"{k} {_usd(v)}" for k, v in p["costs"].items())
    r.claims.append(_c("cost_profile", 1, f"For a fictional small boat landing {sp}, the generated costs are {parts} per lb, {_usd(p['total'])} in total against a stand-in price of {_usd(p['price'])}, a margin of {_usd(p['margin'])} per lb. {SYNTH_SENTENCE}", SYN, 6, "SYNTHETIC", number_note="seed " + str(p["seed"])))
    r.claims.append(_c("cost_profile", 2, f"Generated holding costs: fresh on ice about {_usd(p['fresh_hold_per_day'])} per lb per day, frozen about {_usd(p['frozen_per_month'])} per lb per month; freezing pays only if the frozen price premium beats these. Generated grade split: {int(p['grade_shares']['A']*100)}% grade A, {int(p['grade_shares']['B']*100)}% grade B. {SYNTH_SENTENCE}", SYN, 4, "SYNTHETIC"))
    r.caveats += ["Fictional, seeded numbers scaled to the real " + str(a["last_year"]) + " NOAA annual price. They are not your costs and not industry figures; enter your own to get a real answer."]
    r.data = {"profile": p}
    return r


def wiki_lookup(ctx: Context, species: list[str], region=None, years=None, question: str = "") -> ToolResult:
    """Looks up the mini-wiki (data_real/wiki/wiki.md). Wording comes from the sourced entries, nothing is generated."""
    r = ToolResult("wiki_lookup", species=species)
    hits = wiki.search(question, species, k=2)
    if species and any(re.search(r"\b" + re.escape(w) + r"\b", question, re.I) for w in wiki.STOCK_WORDS + wiki.RULE_WORDS):
        own = [h for h in hits if h[1].species]
        if not own:
            # a status or rules question about a named species must not be answered with a generic definition
            r.refusal = (f"The mini-wiki has no stock-status or rules note for {species[0]} yet. "
                         f"NOAA's species page is the place to check: https://www.fisheries.noaa.gov/species-directory")
            return r
        hits = own
    if not hits:
        r.refusal = "The mini-wiki has no entry for that."
        return r
    top = hits[0][0]
    hits = [h for j, h in enumerate(hits) if j == 0 or h[0] >= max(6, top / 2)]   # a second note only when it is nearly as relevant
    for i, (_, e) in enumerate(hits, 1):
        r.claims.append(Claim(f"WIK{i}", f"{e.title}: {e.text}", f"WIKI:{e.id}", "wiki_lookup.v1", 1, "REAL_OTHER"))
    r.caveats.append("Background notes from public sources, read on " + ", ".join(sorted({e.retrieved for _, e in hits})) +
                     ". Rules and stock status change, so check the source link for the latest.")
    return r


TOOLS = {"price_history": price_history, "price_vs_inflation": price_vs_inflation, "landings_trend": landings_trend,
         "best_region_price": best_region_price, "concentration": concentration, "rec_vs_commercial": rec_vs_commercial,
         "biggest_movers": biggest_movers, "compare_species": compare_species, "data_quality": data_quality,
         "where_found": where_found, "range_shift": range_shift, "seasonal_presence": seasonal_presence,
         "species_background": species_background, "landings_vs_sightings": landings_vs_sightings,
         "recent_sightings_in_region": recent_sightings_in_region, "monthly_timing": monthly_timing, "market_compare": market_compare, "wiki_lookup": wiki_lookup, "obis_profile": obis_profile, "seafood_trade": seafood_trade, "cost_profile": cost_profile, "aquaculture_production": aquaculture_production, "farming_profile": farming_profile}
