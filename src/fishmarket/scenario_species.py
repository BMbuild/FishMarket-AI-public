"""Any species in any region for the fictional scenario.

The hand-made fictional dataset has 64 species-region series. Everything else is generated here, on request,
so a user is never told "not offered":

- What can be picked: the hand-made species for the region, every species NOAA records as landed commercially in
  the matching real region (data_real/crosswalk/scenario_noaa_species.csv), farmed species from
  fishmarket_data/registry/farmed_species_extra.csv, and any name the user types.
- Ranking: species whose usual gear fits the operation come first (pot and trap fisher: crabs, lobster, prawns,
  pot cod, sablefish...), using fishmarket_data/registry/species_keywords.csv and operation_gears.csv.
- Generation: a missing pair gets a monthly first-sale series, a season, storage profiles, market postings and
  quality records, all fictional and deterministic (seeded by the species and region names). Its seasonal shape
  comes from a species-type pattern (generation_patterns.csv); its price level and volume come from real NOAA
  landings where they exist, otherwise from the same species elsewhere in the fictional data, otherwise from a
  category default. It is published under its own source, SRC-GEN-01 (tier C), so the report always says the
  series was generated and confidence is capped at low.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, DEFAULT

GEN_SOURCE = "SRC-GEN-01"
ROOT = Path(__file__).resolve().parents[2]
NOAA_TABLE = ROOT / "data_real" / "crosswalk" / "scenario_noaa_species.csv"
MAX_NAME = 60
NAME_OK = re.compile(r"^[A-Za-z][A-Za-z0-9 ,.'()\-/&]*$")
CATEGORY_PRICE = {"premium": 9.0, "mainstream": 4.0, "price_sensitive": 1.5}
CHANNEL = {"wild_catch": "dockside", "aquaculture": "farm_gate"}


def _reg(cfg: Config) -> Path:
    return cfg.DATA_DIR / "registry"


@lru_cache(maxsize=4)
def patterns(data_dir: str) -> dict:
    df = pd.read_csv(Path(data_dir) / "registry" / "generation_patterns.csv")
    out = {}
    for _, r in df.iterrows():
        out[r["pattern"]] = {"price_idx": [float(x) for x in str(r["price_idx"]).split(";")],
                             "vol_idx": [float(x) for x in str(r["vol_idx"]).split(";")],
                             "open": [int(x) for x in str(r["open_months"]).split(";")],
                             "vol_sigma": float(r["vol_sigma"]), "storage_kind": r["storage_kind"], "note": r["note"]}
    return out


@lru_cache(maxsize=4)
def keywords(data_dir: str) -> list[tuple[re.Pattern, str, list[str]]]:
    df = pd.read_csv(Path(data_dir) / "registry" / "species_keywords.csv", comment="#")
    return [(re.compile(str(r["keyword"]), re.I), str(r["pattern"]), str(r["gears"]).split(";")) for _, r in df.iterrows()]


@lru_cache(maxsize=4)
def op_gears(data_dir: str) -> dict:
    df = pd.read_csv(Path(data_dir) / "registry" / "operation_gears.csv")
    return {r["operation_id"]: (None if r["gears"] == "any" else set(str(r["gears"]).split(";"))) for _, r in df.iterrows()}


@lru_cache(maxsize=4)
def storage_kinds(data_dir: str) -> pd.DataFrame:
    return pd.read_csv(Path(data_dir) / "registry" / "storage_kinds.csv")


@lru_cache(maxsize=4)
def farmed_extra(data_dir: str) -> pd.DataFrame:
    df = pd.read_csv(Path(data_dir) / "registry" / "farmed_species_extra.csv")
    df["region_list"] = df["regions"].str.split(";")
    return df


@lru_cache(maxsize=1)
def noaa_table() -> pd.DataFrame:
    if not NOAA_TABLE.exists():
        return pd.DataFrame(columns=["scenario_region", "species", "price_usd_per_lb", "monthly_lb", "value_5y_usd", "price_trend"])
    return pd.read_csv(NOAA_TABLE)


def clean_name(name: str) -> str:
    """A species name typed by the user, made safe to show and to use as a key (or "" if unusable)."""
    n = re.sub(r"\s+", " ", str(name or "")).strip()[:MAX_NAME]
    if not n or not NAME_OK.match(n):
        return ""
    return n[0].upper() + n[1:]


def classify(species: str, cfg: Config = DEFAULT) -> tuple[str, list[str]]:
    """(pattern, gears) for a species name, from the keyword table (first match wins)."""
    for rx, pat, gears in keywords(str(cfg.DATA_DIR)):
        if rx.search(species):
            return pat, gears
    return "groundfish", ["trawl", "line", "net"]


def fits(species: str, op_id: str, source_type: str, cfg: Config = DEFAULT) -> bool:
    want = op_gears(str(cfg.DATA_DIR)).get(op_id)
    if want is None:
        return True
    gears = set(classify(species, cfg)[1])
    if source_type == "aquaculture":
        gears = {g for g in gears if g.startswith("farm_")} or {"farm_finfish"}
    else:
        gears = {g for g in gears if not g.startswith("farm_")} or gears
    return bool(gears & want)


@dataclass
class Offer:
    species: str
    group: str            # "suggested", "region", "other"
    source_type: str
    handmade: bool        # True when the fictional dataset already has this species in this region


def offers(catalog: pd.DataFrame, region: str, op_row: dict | None = None, cfg: Config = DEFAULT) -> list[Offer]:
    """Every species the user can pick for this region, best fits for the operation first."""
    op_id = (op_row or {}).get("operation_id", "")
    want_type = (op_row or {}).get("species_source_type", "any")
    seen, rows = set(), []

    def add(name, stype, handmade, weight):
        k = name.lower()
        if k in seen:
            return
        seen.add(k)
        rows.append((name, stype, handmade, weight))

    for s in catalog.index:
        if region in catalog.loc[s, "region_list"]:
            add(s, str(catalog.loc[s, "source_type"]), True, 1e12)
    nt = noaa_table()
    for _, r in nt[nt["scenario_region"] == region].iterrows():
        add(str(r["species"]), "wild_catch", False, float(r["value_5y_usd"]))
    fe = farmed_extra(str(cfg.DATA_DIR))
    for _, r in fe.iterrows():
        if region in r["region_list"]:
            add(str(r["species"]), "aquaculture", False, 1e6)
    out = []
    for name, stype, hm, w in rows:
        type_ok = want_type in ("any", stype)
        fit = type_ok and fits(name, op_id, stype, cfg)
        out.append((0 if fit else 1 if type_ok else 2, -w, name, stype, hm))
    out.sort()
    res = [Offer(n, "suggested" if g == 0 else "region", st, hm) for g, _, n, st, hm in out]
    # species from other regions, for anyone who works further afield
    others = set()
    for s in catalog.index:
        others.add((s, str(catalog.loc[s, "source_type"])))
    for _, r in nt.iterrows():
        others.add((str(r["species"]), "wild_catch"))
    for _, r in fe.iterrows():
        others.add((str(r["species"]), "aquaculture"))
    for name, st in sorted(others):
        if name.lower() not in seen:
            seen.add(name.lower())
            res.append(Offer(name, "other", st, False))
    return res


# ---------------------------------------------------------------------------------------------- generation
def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def _category(price: float) -> str:
    return "premium" if price >= 8 else "mainstream" if price >= 2.5 else "price_sensitive"


@dataclass
class Spec:
    species: str
    region: str
    source_type: str
    category: str
    pattern: str
    base_price: float
    monthly_lb: float
    trend: float
    anchor: str           # where the price level came from, in words


def spec_for(species: str, region: str, catalog: pd.DataFrame, cfg: Config = DEFAULT, source_type: str | None = None) -> Spec:
    pat, gears = classify(species, cfg)
    nt = noaa_table()
    fe = farmed_extra(str(cfg.DATA_DIR))
    hit = nt[(nt["species"].str.lower() == species.lower()) & (nt["scenario_region"] == region)]
    anywhere = nt[nt["species"].str.lower() == species.lower()]
    farm = fe[fe["species"].str.lower() == species.lower()]
    if source_type is None:
        if species in catalog.index:
            source_type = str(catalog.loc[species, "source_type"])
        elif len(farm):
            source_type = "aquaculture"
        elif len(anywhere):
            source_type = "wild_catch"
        else:
            source_type = "aquaculture" if all(g.startswith("farm_") for g in gears) else "wild_catch"
    if source_type == "aquaculture" and not pat.startswith("farm_"):
        pat = "farm_shellfish" if patterns(str(cfg.DATA_DIR))[pat]["storage_kind"] in ("shellfish", "crustacean") else "farm_flat"
    if len(hit):
        r = hit.iloc[0]
        price, vol, trend = float(r["price_usd_per_lb"]), float(r["monthly_lb"]), float(r["price_trend"])
        anchor = f"real NOAA landings for {species} in this region ({int(r['last_year'])} price level)"
    elif len(farm):
        r = farm.iloc[0]
        price, vol, trend, anchor = float(r["base_price"]), float(r["monthly_lb"]), 0.01, "the farmed-species reference table"
    elif species in catalog.index:
        price, vol, trend = _from_handmade(species, catalog, cfg)
        anchor = "the same species' fictional series in another region"
    elif len(anywhere):
        r = anywhere.sort_values("value_5y_usd", ascending=False).iloc[0]
        price, vol, trend = float(r["price_usd_per_lb"]), float(r["monthly_lb"]) * 0.2, float(r["price_trend"])
        anchor = f"real NOAA landings for {species} in {r['scenario_region']}"
    else:
        cat = "premium" if pat in ("crab_winter", "lobster", "spiny_lobster", "prawn_spring", "stone_crab") else "mainstream"
        price, vol, trend, anchor = CATEGORY_PRICE[cat], 50_000.0, 0.0, "a default price for this kind of species (no data found)"
    price = max(price, 0.05)
    category = str(catalog.loc[species, "category"]) if species in catalog.index else _category(price)
    return Spec(species, region, source_type, category, pat, round(price, 2), max(vol, 1000.0), trend, anchor)


def _from_handmade(species: str, catalog: pd.DataFrame, cfg: Config) -> tuple[float, float, float]:
    stype = str(catalog.loc[species, "source_type"])
    f = cfg.DATA_DIR / "data" / ("gov_landings.csv" if stype == "wild_catch" else "gov_aquaculture.csv")
    d = pd.read_csv(f)
    d = d[d["species"] == species]
    if d.empty:
        return CATEGORY_PRICE.get(str(catalog.loc[species, "category"]), 4.0), 50_000.0, 0.0
    d = d.sort_values("date").tail(12)
    return float(d["price"].mean()), float(d["volume"].mean()) * 0.25, 0.0


def months_until(as_of: pd.Timestamp) -> pd.DatetimeIndex:
    end = (as_of - pd.DateOffset(months=1)).to_period("M").to_timestamp()
    return pd.date_range("2022-01-01", end, freq="MS")


def generate(spec: Spec, as_of: pd.Timestamp, markets: pd.DataFrame, cfg: Config = DEFAULT) -> dict:
    """All the fictional rows one species-region pair needs, as DataFrames keyed by table name."""
    p = patterns(str(cfg.DATA_DIR))[spec.pattern]
    rng = np.random.default_rng(_seed(spec.species.lower(), spec.region))
    pidx = np.array(p["price_idx"])
    pidx = pidx / pidx.mean()
    vidx = np.array(p["vol_idx"])
    vidx = vidx / vidx.mean()
    dates = months_until(as_of)
    t_mid = dates[-1].year + (dates[-1].month - 6.5) / 12
    rows = []
    for d in dates:
        m = d.month - 1
        yrs = d.year + (d.month - 0.5) / 12 - t_mid
        price = spec.base_price * (1 + spec.trend) ** yrs * pidx[m] * (1 + rng.normal(0, 0.035))
        vol = spec.monthly_lb * vidx[m] * float(np.exp(rng.normal(0, p["vol_sigma"])))
        rows.append({"date": d.strftime("%Y-%m-%d"), "region": spec.region, "species": spec.species, "source_type": spec.source_type,
                     "price": f"{max(price, 0.01):.2f}", "volume": f"{max(vol, 1.0):.1f}", "unit": "lb",
                     "channel": CHANNEL[spec.source_type], "source_id": GEN_SOURCE, "retrieved_on": as_of.strftime("%Y-%m-%d")})
    series = pd.DataFrame(rows)
    season = pd.DataFrame([{"species": spec.species, "region": spec.region, "open_months": ";".join(map(str, p["open"])),
                            "method": "generated", "note": p["note"]}])
    sk = storage_kinds(str(cfg.DATA_DIR))
    storage = sk[sk["storage_kind"] == p["storage_kind"]].drop(columns=["storage_kind"]).assign(species=spec.species)
    mk = markets[markets["region"] == spec.region]
    factor = {"dock_auction": 1.00, "seafood_exchange": 1.04, "wholesale_market": 1.08}
    mrows = []
    recent = series.tail(12)
    for _, m in mk.iterrows():
        f = factor.get(str(m["market_type"]), 1.0)
        for _, r in recent.iterrows():
            mrows.append({"date": r["date"], "market_id": m["market_id"], "region": spec.region, "species": spec.species,
                          "source_type": spec.source_type, "price": round(float(r["price"]) * f * (1 + rng.normal(0, 0.03)), 2),
                          "unit": "lb", "currency": "USD", "channel": str(m["market_type"]), "source_id": "SRC-MKT-01",
                          "retrieved_on": as_of.strftime("%Y-%m-%d")})
    mprices = pd.DataFrame(mrows)
    qrows = []
    start = pd.Timestamp(cfg.QUALITY_WINDOW_START)
    span = max((as_of - start).days, 30)
    for i in range(10):
        day = start + pd.Timedelta(days=int(rng.integers(0, span)))
        qrows.append({"record_id": f"QR-GEN-{_seed(spec.species, spec.region) % 100000:05d}-{i:02d}", "date": day.strftime("%Y-%m-%d"),
                      "species": spec.species, "region": spec.region,
                      "market_id": (mk["market_id"].iloc[i % len(mk)] if len(mk) else ""), "grade": "A" if rng.random() < 0.5 else "B",
                      "freshness_days": int(rng.integers(1, 6)), "handling": "chilled", "temp_c": round(float(rng.normal(1.5, 0.8)), 1),
                      "verification_status": "VERIFIED" if rng.random() < 0.7 else "UNVERIFIED", "inspector_org": "QA-GEN",
                      "notes": "Generated record (fictional)", "source_id": "SRC-QLT-01", "retrieved_on": as_of.strftime("%Y-%m-%d")})
    return {"series": series, "season": season, "storage": storage, "market_prices": mprices, "quality": pd.DataFrame(qrows)}


def registry_row(pairs: list[str], as_of: pd.Timestamp) -> dict:
    return {"source_id": GEN_SOURCE, "name": "Generated for this scenario (fictional)", "owner": "FishMarket AI (Python generator)",
            "source_kind": "generated", "trust_tier": "C", "update_cadence_days": 35, "last_updated": as_of - pd.Timedelta(days=10),
            "file": "(generated in memory)", "has_volume": True, "price_basis": "first_sale", "expected_markup_vs_first_sale": 1.0,
            "covers": "Generated on request for: " + ", ".join(pairs),
            "notes": "Python generated this series because the fictional dataset has none for it. Seasonal shape from a species-type "
                     "pattern; price level from real NOAA landings where available. Caps confidence at low.",
            "dataset_kind": "price_series"}


def missing_pairs(species: list[str], region: str, catalog: pd.DataFrame) -> list[str]:
    return [s for s in species if not (s in catalog.index and region in catalog.loc[s, "region_list"])]


def augment(species: list[str], region: str, catalog: pd.DataFrame, registry: pd.DataFrame, raws: dict, ex, as_of: pd.Timestamp,
            cfg: Config = DEFAULT, source_type: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, list[Spec]]:
    """Adds generated data for every species that has no hand-made series in `region`.
    Returns (catalog, registry, specs); `raws` and `ex` (Extras) are extended in place."""
    miss = missing_pairs(species, region, catalog)
    if not miss:
        return catalog, registry, []
    specs = [spec_for(s, region, catalog, cfg, source_type=None if s in catalog.index else source_type) for s in miss]
    parts = [generate(sp, as_of, ex.markets, cfg) for sp in specs]
    recs = {s: dict(catalog.loc[s]) for s in catalog.index}
    for sp in specs:
        if sp.species in recs:
            r = recs[sp.species]
            r["region_list"] = list(r["region_list"]) + [region]
            r["regions"] = ";".join(r["region_list"])
        else:
            recs[sp.species] = {"species": sp.species, "category": sp.category, "source_type": sp.source_type,
                                "regions": region, "region_list": [region]}
    cat = pd.DataFrame(list(recs.values())).set_index("species", drop=False)
    reg = registry.copy()
    row = registry_row([f"{sp.species}|{region}" for sp in specs], as_of)
    reg.loc[GEN_SOURCE] = {k: row.get(k) for k in reg.columns}
    raws[GEN_SOURCE] = pd.concat([raws.get(GEN_SOURCE, pd.DataFrame())] + [p["series"] for p in parts], ignore_index=True).astype(str)
    ex.add_generated(parts)
    return cat, reg, specs
