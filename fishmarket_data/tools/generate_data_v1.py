#!/usr/bin/env python3
"""Generate the FICTIONAL FishMarket AI demo dataset.

Everything produced here is invented. No real market, agency, price, or company
is represented. The output is deterministic (seeded) so the team can regenerate
it exactly.

Usage:  python generate_data.py <output_dir>
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261015
AS_OF = "2026-10-15"          # the fixed "today" for every demo run and test
MONTHS = pd.date_range("2022-01-01", "2026-09-01", freq="MS")
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
CLIP = 3.0  # truncate noise at +/- 3 sigma so clean data stays within tolerances

REGION_FACTOR = {"Gulf": 0.97, "Northeast": 1.06,
                 "Pacific Northwest": 1.04, "Southeast": 0.96}

# Planted truth. price_idx / vol_idx are Jan..Dec seasonal multipliers.
SPECIES = {
    "American lobster": dict(
        category="premium", source_type="wild_catch", base_price=11.0, trend=0.03,
        price_idx=[1.15, 1.00, 0.95, 0.93, 0.92, 0.90, 0.88, 0.85, 0.88, 0.95, 1.10, 1.28],
        vol_idx=[0.5, 0.4, 0.4, 0.5, 0.7, 1.0, 1.4, 1.7, 1.7, 1.4, 0.9, 0.6], vol_sigma=0.08),
    "Sea scallops": dict(
        category="premium", source_type="wild_catch", base_price=14.0, trend=0.02,
        price_idx=[1.10, 1.00, 0.95, 0.92, 0.90, 0.90, 0.92, 0.95, 0.98, 1.00, 1.10, 1.20],
        vol_idx=[1.1, 1.0, 1.0, 1.0, 0.9, 0.9, 0.9, 0.9, 1.0, 1.1, 1.1, 1.1], vol_sigma=0.08),
    "Wild salmon": dict(
        category="mainstream", source_type="wild_catch", base_price=7.2, trend=0.01,
        price_idx=[1.16, 1.22, 1.14, 1.05, 0.95, 0.88, 0.82, 0.83, 0.90, 1.00, 1.08, 1.15],
        vol_idx=[0.15, 0.10, 0.10, 0.2, 0.5, 1.4, 3.0, 3.2, 2.0, 0.7, 0.3, 0.2], vol_sigma=0.08),
    "Farmed salmon": dict(
        category="mainstream", source_type="aquaculture", base_price=6.5, trend=0.025,
        price_idx=[1.00, 0.98, 0.97, 0.97, 0.98, 0.98, 0.97, 0.97, 0.98, 1.00, 1.015, 1.03],
        vol_idx=[1.0] * 12, vol_sigma=0.03),
    "Gulf shrimp": dict(
        category="mainstream", source_type="wild_catch", base_price=4.4, trend=-0.01,
        price_idx=[1.06, 1.12, 1.16, 1.10, 1.04, 0.99, 0.94, 0.90, 0.88, 0.88, 0.95, 1.02],
        vol_idx=[0.4, 0.4, 0.5, 0.6, 0.8, 1.0, 1.3, 1.6, 1.7, 1.5, 0.9, 0.5], vol_sigma=0.08),
    "Cod": dict(
        category="mainstream", source_type="wild_catch", base_price=5.8, trend=-0.03,
        price_idx=[1.10, 1.17, 1.10, 1.02, 0.98, 0.96, 0.95, 0.94, 0.94, 0.94, 0.97, 1.00],
        vol_idx=[1.1, 1.1, 1.0, 0.9, 0.9, 0.8, 0.8, 0.8, 0.9, 1.0, 1.1, 1.1], vol_sigma=0.08),
    "Yellowfin tuna": dict(
        category="price_sensitive", source_type="wild_catch", base_price=2.1, trend=0.0,
        price_idx=[1.0, 1.0, 1.0, 1.01, 1.02, 1.02, 1.02, 1.01, 1.0, 1.0, 1.0, 1.0],
        vol_idx=[1.0] * 12, vol_sigma=0.08),
    "Catfish": dict(
        category="price_sensitive", source_type="aquaculture", base_price=2.4, trend=0.01,
        price_idx=[1.0, 1.0, 1.0, 1.0, 1.01, 1.02, 1.02, 1.01, 1.0, 1.0, 1.0, 1.0],
        vol_idx=[1.0] * 12, vol_sigma=0.03),
    "Tilapia": dict(
        category="price_sensitive", source_type="aquaculture", base_price=2.0, trend=-0.02,
        price_idx=[1.0, 1.0, 1.0, 1.0, 1.0, 1.01, 1.01, 1.0, 1.0, 1.0, 1.0, 1.0],
        vol_idx=[1.0] * 12, vol_sigma=0.03),
    "Sturgeon caviar": dict(
        category="premium", source_type="aquaculture", base_price=780.0, trend=0.04,
        price_idx=[1.05, 1.10, 1.00, 0.95, 0.93, 0.90, 0.90, 0.92, 0.95, 1.00, 1.12, 1.35],
        vol_idx=[0.9, 0.9, 0.9, 1.0, 1.0, 1.0, 1.0, 1.0, 1.1, 1.2, 1.2, 1.0], vol_sigma=0.03),
}

# (species, region, base monthly volume in lb)
COMBOS = [
    ("American lobster", "Northeast", 2_400_000),
    ("Sea scallops", "Northeast", 600_000),
    ("Wild salmon", "Pacific Northwest", 3_000_000),
    ("Farmed salmon", "Northeast", 1_800_000),
    ("Farmed salmon", "Pacific Northwest", 2_200_000),
    ("Gulf shrimp", "Gulf", 4_500_000),
    ("Gulf shrimp", "Southeast", 1_600_000),
    ("Cod", "Northeast", 1_900_000),
    ("Cod", "Pacific Northwest", 1_100_000),
    ("Yellowfin tuna", "Gulf", 2_200_000),
    ("Yellowfin tuna", "Southeast", 1_700_000),
    ("Catfish", "Southeast", 3_200_000),
    ("Catfish", "Gulf", 1_500_000),
    ("Tilapia", "Southeast", 1_400_000),
    ("Tilapia", "Gulf", 800_000),
    ("Sturgeon caviar", "Pacific Northwest", 4_000),
    ("Sturgeon caviar", "Southeast", 3_000),
]

IND_SKIP = {("Wild salmon", "Pacific Northwest"), ("Sturgeon caviar", "Southeast")}
TRD_COMBOS = {("Gulf shrimp", "Gulf"), ("Gulf shrimp", "Southeast"),
              ("American lobster", "Northeast"), ("Cod", "Northeast"),
              ("Yellowfin tuna", "Gulf"), ("Yellowfin tuna", "Southeast")}

SOURCES = [
    dict(source_id="SRC-GOV-01", name="National Fisheries Landings Program (fictional)",
         owner="Department of Ocean Statistics (fictional)", source_kind="government_statistics",
         trust_tier="A", update_cadence_days=35, last_updated="2026-10-05",
         file="data/gov_landings.csv", has_volume="true", price_basis="first_sale",
         expected_markup_vs_first_sale=1.00,
         covers="Wild-catch species: lobster, scallops, wild salmon, shrimp, cod, tuna",
         notes="Dockside first-sale price and landings volume."),
    dict(source_id="SRC-GOV-02", name="National Aquaculture Survey (fictional)",
         owner="Department of Ocean Statistics (fictional)", source_kind="government_statistics",
         trust_tier="A", update_cadence_days=35, last_updated="2026-10-02",
         file="data/gov_aquaculture.csv", has_volume="true", price_basis="first_sale",
         expected_markup_vs_first_sale=1.00,
         covers="Farmed species: caviar, farmed salmon, catfish, tilapia",
         notes="Farm-gate price and harvest volume."),
    dict(source_id="SRC-IND-01", name="Coastal Seafood Association Wholesale Report (fictional)",
         owner="Coastal Seafood Association (fictional)", source_kind="industry_association",
         trust_tier="B", update_cadence_days=35, last_updated="2026-09-28",
         file="data/assoc_wholesale.csv", has_volume="true", price_basis="wholesale",
         expected_markup_vs_first_sale=1.15,
         covers="15 of 17 species-region series; not wild salmon (Pacific Northwest) or caviar (Southeast)",
         notes="Wholesale price runs about 15 percent above first-sale price. Volume covers association members only."),
    dict(source_id="SRC-TRD-01", name="Seafood Trade Weekly Price Notes (fictional)",
         owner="Seafood Trade Weekly (fictional)", source_kind="trade_press",
         trust_tier="C", update_cadence_days=35, last_updated="2026-10-12",
         file="data/trade_price_notes.csv", has_volume="false", price_basis="first_sale",
         expected_markup_vs_first_sale=1.00,
         covers="Six series: shrimp (Gulf, Southeast), lobster, cod, tuna (Gulf, Southeast)",
         notes="Price quotes only, noisier than official data. No volume."),
    dict(source_id="SRC-SMP-01", name="Team Sample Dataset (fictional)",
         owner="Project team (fictional)", source_kind="synthetic_sample",
         trust_tier="D", update_cadence_days=365, last_updated="2026-10-01",
         file="data/sample_fallback.csv", has_volume="true", price_basis="first_sale",
         expected_markup_vs_first_sale=1.00,
         covers="All 17 series, last 24 months only",
         notes="Fallback only. Always labeled as sample data. Caps confidence at low."),
]

COLUMNS = ["date", "region", "species", "source_type", "price", "volume",
           "unit", "channel", "source_id", "retrieved_on"]


def trunc_normal(rng, sigma, size):
    return np.clip(rng.normal(0.0, sigma, size), -CLIP * sigma, CLIP * sigma)


def build_truth(rng):
    rows = []
    n = len(MONTHS)
    for species, region, base_vol in COMBOS:
        sp = SPECIES[species]
        mkt = trunc_normal(rng, 0.025, n)
        vnoise = trunc_normal(rng, sp["vol_sigma"], n)
        for i, d in enumerate(MONTHS):
            m = d.month - 1
            years = i / 12.0
            price = (sp["base_price"] * REGION_FACTOR[region] * sp["price_idx"][m]
                     * (1 + sp["trend"]) ** years * np.exp(mkt[i]))
            vol = base_vol * sp["vol_idx"][m] * np.exp(vnoise[i])
            rows.append(dict(date=d, species=species, region=region,
                             source_type=sp["source_type"], price=price, volume=vol))
    return pd.DataFrame(rows)


def make_source(truth, rng, source_id, combos, price_mult, price_sigma,
                vol_mult, vol_sigma, channel, retrieved_on, with_volume=True,
                months_from=None):
    parts = []
    for species, region in combos:
        t = truth[(truth.species == species) & (truth.region == region)].copy()
        if months_from is not None:
            t = t[t.date >= pd.Timestamp(months_from)]
        n = len(t)
        t["price"] = t["price"] * price_mult * np.exp(trunc_normal(rng, price_sigma, n))
        if with_volume:
            t["volume"] = t["volume"] * vol_mult * np.exp(trunc_normal(rng, vol_sigma, n))
        else:
            t["volume"] = np.nan
        parts.append(t)
    df = pd.concat(parts, ignore_index=True)
    df["unit"] = "lb"
    df["channel"] = channel
    df["source_id"] = source_id
    df["retrieved_on"] = retrieved_on
    df["price"] = df["price"].round(2)
    df["volume"] = df["volume"].round(0)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df.sort_values(["species", "region", "date"]).reset_index(drop=True)
    return df[COLUMNS]


def channel_for(source_type, kind):
    if kind == "gov":
        return "dockside" if source_type == "wild_catch" else "farm_gate"
    return kind


def write_csv(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def planted_cases(gov1, gov2, ind, trd, registry_df):
    out = {}
    manifest = []

    # PP-STALE: wholesale report stops in March 2026 and says so
    stale = ind[ind["date"] <= "2026-03-01"].copy()
    stale["retrieved_on"] = "2026-03-14"
    out["planted/pp_stale_wholesale.csv"] = stale
    reg = registry_df.copy()
    reg.loc[reg.source_id == "SRC-IND-01", "last_updated"] = "2026-03-14"
    out["planted/registry_planted.csv"] = reg
    manifest.append(dict(
        case_id="PP-STALE", file="planted/pp_stale_wholesale.csv",
        replaces_source_id="SRC-IND-01", registry_file="planted/registry_planted.csv",
        injected="Wholesale report data stops at 2026-03 and registry last_updated is 2026-03-14 (about 215 days before the demo date; cadence is 35 days).",
        expected_flags=["stale_data"],
        expected_flags_by_series={f"{s}|{r}": ["stale_data"] for s, r in ind[["species", "region"]].drop_duplicates().itertuples(index=False)},
        affected_series="Every series that SRC-IND-01 covers",
        expected_effect="SRC-IND-01 is excluded as stale. Series left with one source rate Medium (single source).",
        expected_trust_for_affected_series="medium"))

    # PP-UNIT: cod Northeast reported in kilograms for six months
    unit = gov1.copy()
    mask = ((unit.species == "Cod") & (unit.region == "Northeast")
            & (unit.date >= "2026-01-01") & (unit.date <= "2026-06-01"))
    unit.loc[mask, "price"] = (unit.loc[mask, "price"] * 2.2046).round(2)
    unit.loc[mask, "volume"] = (unit.loc[mask, "volume"] / 2.2046).round(0)
    unit.loc[mask, "unit"] = "kg"
    out["planted/pp_unit_error_landings.csv"] = unit
    manifest.append(dict(
        case_id="PP-UNIT", file="planted/pp_unit_error_landings.csv",
        replaces_source_id="SRC-GOV-01", registry_file="registry/source_registry.csv",
        injected="Cod (Northeast) rows for 2026-01 to 2026-06 are reported in kg: price multiplied by 2.2046, volume divided by 2.2046, unit set to 'kg'.",
        expected_flags=["unit_mismatch"],
        expected_flags_by_series={"Cod|Northeast": ["unit_mismatch"]},
        affected_series="Cod, Northeast",
        expected_effect="Gate converts kg to lb; converted values match data/gov_landings.csv within 0.5 percent. Minor warning only.",
        expected_trust_for_affected_series="medium"))

    # PP-OUTLIER: one tilapia price is eight times too high
    outl = gov2.copy()
    m2 = ((outl.species == "Tilapia") & (outl.region == "Southeast") & (outl.date == "2026-04-01"))
    outl.loc[m2, "price"] = (outl.loc[m2, "price"] * 8).round(2)
    out["planted/pp_outlier_aquaculture.csv"] = outl
    manifest.append(dict(
        case_id="PP-OUTLIER", file="planted/pp_outlier_aquaculture.csv",
        replaces_source_id="SRC-GOV-02", registry_file="registry/source_registry.csv",
        injected="Tilapia (Southeast) price for 2026-04 is multiplied by 8.",
        expected_flags=["outlier"],
        expected_flags_by_series={"Tilapia|Southeast": ["outlier"]},
        affected_series="Tilapia, Southeast",
        expected_effect="Gate flags and removes the single bad month. Minor warning only.",
        expected_trust_for_affected_series="medium"))

    # PP-CONFLICT: trade press quotes Gulf shrimp 35 percent below official data
    conf = trd.copy()
    m3 = ((conf.species == "Gulf shrimp") & (conf.region == "Gulf")
          & (conf.date >= "2026-05-01") & (conf.date <= "2026-09-01"))
    conf.loc[m3, "price"] = (conf.loc[m3, "price"] * 0.65).round(2)
    out["planted/pp_conflict_trade_notes.csv"] = conf
    manifest.append(dict(
        case_id="PP-CONFLICT", file="planted/pp_conflict_trade_notes.csv",
        replaces_source_id="SRC-TRD-01", registry_file="registry/source_registry.csv",
        injected="Gulf shrimp (Gulf) trade-press quotes for 2026-05 to 2026-09 are multiplied by 0.65.",
        expected_flags=["source_disagreement"],
        expected_flags_by_series={"Gulf shrimp|Gulf": ["source_disagreement"]},
        affected_series="Gulf shrimp, Gulf",
        expected_effect="Cross-source check flags SRC-TRD-01 against SRC-GOV-01 (deviation over 10 percent). Trust drops to Low and the report says the sources disagree.",
        expected_trust_for_affected_series="low"))

    # PP-DUPMISS: duplicates, missing values, and out-of-range dates
    dm = gov1.copy()
    dup_rows = dm[(dm.species == "American lobster") & (dm.region == "Northeast")
                  & (dm.date >= "2025-01-01") & (dm.date <= "2025-06-01")]
    nullp = (dm.species == "Gulf shrimp") & (dm.region == "Gulf") & (dm.date >= "2025-03-01") & (dm.date <= "2025-07-01")
    nullv = (dm.species == "Yellowfin tuna") & (dm.region == "Gulf") & (dm.date >= "2025-01-01") & (dm.date <= "2025-03-01")
    dm.loc[nullp, "price"] = np.nan
    dm.loc[nullv, "volume"] = np.nan
    base = dm[(dm.species == "Cod") & (dm.region == "Northeast") & (dm.date == "2026-08-01")]
    future = pd.concat([base.assign(date="2027-02-01"), base.assign(date="2027-03-01")])
    dm = pd.concat([dm, dup_rows, future], ignore_index=True)
    out["planted/pp_dupmiss_landings.csv"] = dm
    manifest.append(dict(
        case_id="PP-DUPMISS", file="planted/pp_dupmiss_landings.csv",
        replaces_source_id="SRC-GOV-01", registry_file="registry/source_registry.csv",
        injected="6 duplicated lobster (Northeast) rows for 2025-01..2025-06; 5 blank prices for shrimp (Gulf) 2025-03..2025-07; 3 blank volumes for tuna (Gulf) 2025-01..2025-03; 2 rows dated 2027-02 and 2027-03 (after the demo date).",
        expected_flags=["duplicates", "missing_values", "date_range"],
        expected_flags_by_series={"American lobster|Northeast": ["duplicates"], "Gulf shrimp|Gulf": ["missing_values"], "Yellowfin tuna|Gulf": ["missing_values"], "Cod|Northeast": ["date_range"]},
        affected_series="Lobster (Northeast), Gulf shrimp (Gulf), Yellowfin tuna (Gulf), Cod (Northeast)",
        expected_effect="Gate removes 6 duplicates and 2 future-dated rows, and flags 5 missing prices and 3 missing volumes without inventing values. Minor warnings only.",
        expected_trust_for_affected_series="medium"))
    return out, manifest


def seasonal_profile(price_series_df):
    """Average of (month price / that calendar year's mean), over full years 2022-2025."""
    df = price_series_df.copy()
    df["d"] = pd.to_datetime(df["date"])
    df["y"] = df.d.dt.year
    df["m"] = df.d.dt.month
    df = df[df.y <= 2025]
    df["ratio"] = df.price / df.groupby("y").price.transform("mean")
    return df.groupby("m").ratio.mean().reindex(range(1, 13)).tolist()


NOW = pd.Timestamp(AS_OF).month - 1      # 0-based index of the demo month (October)
HOLD_THRESHOLD = 1.10
MIN_MARGIN = 0.03                        # a golden case may not sit this close to the threshold


def season_strength(price_idx):
    spread = max(price_idx) - min(price_idx)
    return "strong" if spread >= 0.20 else ("mild" if spread >= 0.05 else "flat")


def next3_ratio(idx):
    """Best of the next three months' seasonal price index over this month's."""
    nxt = [idx[(NOW + k) % 12] for k in (1, 2, 3)]
    return max(nxt) / idx[NOW]


def build_ground_truth(primary):
    gt = {}
    for species, region, _ in COMBOS:
        sp = SPECIES[species]
        s = primary[(primary.species == species) & (primary.region == region)].sort_values("date")
        prof = seasonal_profile(s)
        last12 = s.tail(12).price.mean()
        prev12 = s.iloc[-24:-12].price.mean()
        gt[f"{species}|{region}"] = dict(
            species=species, region=region, category=sp["category"],
            seasonality_strength=season_strength(sp["price_idx"]),
            planted_trend_pct_per_year=sp["trend"] * 100,
            planted_peak_price_month=MONTH_NAMES[int(np.argmax(sp["price_idx"]))],
            planted_price_idx=sp["price_idx"],
            planted_best_next3_vs_now_ratio=round(next3_ratio(sp["price_idx"]), 3),
            measured_seasonal_price_index=[round(x, 4) for x in prof],
            measured_peak_price_month=MONTH_NAMES[int(np.argmax(prof))],
            measured_best_next3_vs_now_ratio=round(next3_ratio(prof), 3),
            measured_yoy_price_change_pct=round((last12 / prev12 - 1) * 100, 2),
            measured_supply_yoy_last3_pct=round(
                (float(s.tail(3).volume.mean() / s.iloc[-15:-12].volume.mean()) - 1) * 100, 2),
            latest_month=s.date.iloc[-1], latest_price=float(s.price.iloc[-1]))
    return gt


def driver_tags(direction, yoy):
    """Required and forbidden driver tags. Trend tags are only constrained when the
    measured year-over-year change is clearly on one side of the 2.0 percent rule."""
    required, forbidden = [], []
    (required if direction == "hold" else forbidden).append("seasonal_peak_ahead")
    if yoy <= -2.5:
        required.append("declining_trend"); forbidden.append("rising_trend")
    elif yoy >= 2.5:
        required.append("rising_trend"); forbidden.append("declining_trend")
    elif abs(yoy) <= 1.5:
        forbidden += ["rising_trend", "declining_trend"]
    return required, forbidden


def golden_cases(gt):
    # (id, kind, name, region, business_type, species, segment, volume, planted_cases,
    #  expected_trust, required_gate_flags)
    specs = [
        ("G01", "preset", "Gulf Coast shrimp boat, mainstream buyers", "Gulf", "wild_catch", "Gulf shrimp", "mainstream", 40000, [], "high", []),
        ("G02", "preset", "New England lobster fisher, premium restaurants", "Northeast", "wild_catch", "American lobster", "premium", 25000, [], "high", []),
        ("G03", "preset", "Pacific Northwest salmon cooperative, mixed buyers", "Pacific Northwest", "cooperative", "Wild salmon", "mainstream", 120000, [], "medium", ["single_source"]),
        ("G04", "preset", "Southeastern catfish farm, price-sensitive buyers", "Southeast", "aquaculture", "Catfish", "price_sensitive", 90000, [], "high", []),
        ("G05", "preset", "Pacific Northwest sturgeon farm, luxury caviar buyers", "Pacific Northwest", "aquaculture", "Sturgeon caviar", "premium", 300, [], "high", []),
        ("G06", "preset", "Gulf Coast shrimp boat with planted data problems", "Gulf", "wild_catch", "Gulf shrimp", "mainstream", 40000, ["PP-CONFLICT", "PP-STALE"], "low", ["source_disagreement", "stale_data"]),
        ("G07", "variant", "Northeast scallop distributor, premium restaurants", "Northeast", "distributor", "Sea scallops", "premium", 15000, [], "high", []),
        ("G08", "variant", "Southeastern tilapia farm, price-sensitive buyers", "Southeast", "aquaculture", "Tilapia", "price_sensitive", 70000, [], "high", []),
        ("G09", "variant", "Gulf tuna distributor, price-sensitive buyers", "Gulf", "distributor", "Yellowfin tuna", "price_sensitive", 60000, [], "high", []),
        ("G10", "variant", "Northeast cod fisher, mainstream buyers", "Northeast", "wild_catch", "Cod", "mainstream", 30000, [], "high", []),
        ("G11", "variant", "Pacific Northwest farmed-salmon cooperative, mainstream buyers", "Pacific Northwest", "cooperative", "Farmed salmon", "mainstream", 110000, [], "high", []),
        ("G12", "variant", "Southeastern sturgeon farm, luxury caviar buyers", "Southeast", "aquaculture", "Sturgeon caviar", "premium", 200, [], "medium", ["single_source"]),
    ]
    cases = []
    for cid, kind, name, region, btype, species, seg, vol, planted, trust, gate_flags in specs:
        v = gt[f"{species}|{region}"]
        planted_dir = "hold" if v["planted_best_next3_vs_now_ratio"] >= HOLD_THRESHOLD else "sell_now"
        measured_dir = "hold" if v["measured_best_next3_vs_now_ratio"] >= HOLD_THRESHOLD else "sell_now"
        if planted_dir != measured_dir:
            raise SystemExit(f"{cid}: planted and measured direction disagree for {species}|{region}")
        if abs(v["measured_best_next3_vs_now_ratio"] - HOLD_THRESHOLD) < MIN_MARGIN:
            raise SystemExit(f"{cid}: ratio too close to the hold threshold for {species}|{region}")
        req, forb = driver_tags(measured_dir, v["measured_yoy_price_change_pct"])
        strong = v["seasonality_strength"] == "strong"
        cases.append(dict(
            case_id=cid, kind=kind, name=name,
            profile=dict(region=region, business_type=btype, species=[species],
                         customer_segment=seg, volume_lb_per_month=vol, as_of=AS_OF,
                         question="Should I sell now or hold over the next 3 months?"),
            planted_cases=planted,
            expected=dict(
                direction=measured_dir,
                direction_rule="hold if the best of the next 3 months' seasonal price index is at least 1.10 times this month's index, otherwise sell_now",
                best_next3_vs_now_ratio=v["measured_best_next3_vs_now_ratio"],
                seasonality_strength=v["seasonality_strength"],
                peak_month=v["measured_peak_price_month"] if strong else None,
                expected_trust=trust,
                required_gate_flags=gate_flags,
                required_driver_tags=req,
                forbidden_driver_tags=forb,
                required_stat_kinds=["seasonal_price_index", "yoy_price_change", "supply_yoy_change"],
                min_cited_stats=3,
                forbidden=["any number that is not in the statistics table"])))
    return cases


README = """# FishMarket AI fictional dataset

ALL DATA HERE IS FICTIONAL. No real market, agency, price, or company is
represented. Source names are invented stand-ins that imitate real source types
so the verification layer can be demonstrated realistically.

Fixed demo date ("today" for every run and test): **{as_of}**.
Data covers 2022-01 to 2026-09 (57 months). Regenerate exactly with
`python tools/generate_data.py <dir>` (seed {seed}).

## Layout

| Path | Purpose |
| --- | --- |
| `registry/source_registry.csv` | The approved sources: owner, tier, cadence, last updated, file, price basis, expected wholesale markup |
| `registry/species_catalog.csv` | Ten species with category, source type, and regions |
| `data/gov_landings.csv` | SRC-GOV-01, Tier A, wild-catch dockside price and landings (513 rows) |
| `data/gov_aquaculture.csv` | SRC-GOV-02, Tier A, farm-gate price and harvest (456 rows) |
| `data/assoc_wholesale.csv` | SRC-IND-01, Tier B, wholesale price (about 15 percent above first-sale) and member volume (855 rows) |
| `data/trade_price_notes.csv` | SRC-TRD-01, Tier C, price quotes only, no volume (342 rows) |
| `data/sample_fallback.csv` | SRC-SMP-01, Tier D, 24 months, fallback only (408 rows) |
| `planted/` | Five copies of sources with one deliberate defect each, plus `registry_planted.csv` and `planted_manifest.json` |
| `tests_only/` | `ground_truth.json` and `golden_cases.json`. **The pipeline must never read this folder.** Tests only. |
| `tools/` | `generate_data.py` and `validate_data.py` |

## Columns (all data files)

`date` (first of month), `region`, `species`, `source_type` (wild_catch or aquaculture),
`price` (per `unit`), `volume` (in `unit`), `unit` (lb; kg in one planted case),
`channel`, `source_id`, `retrieved_on` (the source's last-updated date).

SRC-TRD-01 has no volume by design (registry `has_volume` is false), so blank
volume there is not an error.

## Planted patterns (the known truth the tests rely on)

- Strong seasonal price peaks: lobster, scallops, caviar in December; wild salmon and
  cod in February; Gulf shrimp in March. Only these species have a reliable peak month.
- Mild seasonality: farmed salmon (about 6 percent swing, small holiday uplift). Its
  peak month is not reliably recoverable, so no test may require it.
- Flat seasonality: tuna, catfish, tilapia. No test may require a peak month.
- Trends per year: lobster +3%, scallops +2%, wild salmon +1%, farmed salmon +2.5%,
  shrimp -1%, cod -3%, tuna 0%, catfish +1%, tilapia -2%, caviar +4%.
- Regional price factors: Gulf 0.97, Northeast 1.06, Pacific Northwest 1.04, Southeast 0.96.
- Sources agree within 10 percent after dividing wholesale by its 1.15 markup.
- Two series have only one source: wild salmon (Pacific Northwest) and caviar (Southeast).

## Planted problem cases

| Case | Defect | Must be flagged as |
| --- | --- | --- |
| PP-STALE | Wholesale report stops at 2026-03 | stale_data |
| PP-UNIT | Cod (Northeast) 2026-01..06 reported in kg | unit_mismatch |
| PP-OUTLIER | Tilapia (Southeast) 2026-04 price x8 | outlier |
| PP-CONFLICT | Gulf shrimp trade quotes 2026-05..09 at 65 percent of official | source_disagreement |
| PP-DUPMISS | 6 duplicates, 5 blank prices, 3 blank volumes, 2 future dates | duplicates, missing_values, date_range |

See `planted/planted_manifest.json`. Tests should use `expected_flags_by_series`, which gives the exact flags each
series must show and lists every affected series (file paths in the manifest are relative to this folder).

## Golden cases

`tests_only/golden_cases.json` holds 12 cases (6 presets, 6 variants). Each lists the
profile and an `expected` block. Every expectation is computed from the MEASURED data,
and the generator stops if the measured and planted answers disagree or if a case sits
within 0.03 of the hold threshold.

- **direction**: `hold` if the best of the next three months' seasonal price index is at
  least 1.10 times this month's index, else `sell_now`. "This month" is the month of the
  fixed demo date (October). The seasonal index is each month's price divided by that
  calendar year's mean price, averaged over the complete years 2022 to 2025.
- **peak_month**: only set for strong-seasonality species; otherwise null and not tested.
- **expected_trust**: high, medium, or low, from the trust rules in the PRD.
- **required_gate_flags**: set by the Python verification gate, not by the model
  (`single_source`, `source_disagreement`, `stale_data`).
- **required_driver_tags / forbidden_driver_tags**: tags the analyst agent must (or must
  not) return. Vocabulary: `seasonal_peak_ahead` (direction is hold), `declining_trend`
  (year-over-year price change at or below -2.0 percent), `rising_trend` (at or above
  +2.0 percent). A trend tag is only required or forbidden when the measured change is
  at least 0.5 points clear of the threshold; in the gap either answer passes.
- **required_stat_kinds**: `seasonal_price_index`, `yoy_price_change`, `supply_yoy_change`
  (last three months' volume against the same three months a year earlier).
"""


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "fishmarket_data")
    rng = np.random.default_rng(SEED)
    truth = build_truth(rng)

    all_combos = [(s, r) for s, r, _ in COMBOS]
    wild = [(s, r) for s, r in all_combos if SPECIES[s]["source_type"] == "wild_catch"]
    farm = [(s, r) for s, r in all_combos if SPECIES[s]["source_type"] == "aquaculture"]

    def mk(source_id, combos, **kw):
        return make_source(truth, rng, source_id, combos, **kw)

    gov1 = mk("SRC-GOV-01", wild, price_mult=1.0, price_sigma=0.010, vol_mult=1.0,
              vol_sigma=0.010, channel="dockside", retrieved_on="2026-10-05")
    gov2 = mk("SRC-GOV-02", farm, price_mult=1.0, price_sigma=0.010, vol_mult=1.0,
              vol_sigma=0.010, channel="farm_gate", retrieved_on="2026-10-02")
    ind = mk("SRC-IND-01", [c for c in all_combos if c not in IND_SKIP], price_mult=1.15,
             price_sigma=0.012, vol_mult=0.6, vol_sigma=0.05, channel="wholesale",
             retrieved_on="2026-09-28")
    trd = mk("SRC-TRD-01", sorted(TRD_COMBOS), price_mult=1.0, price_sigma=0.025,
             vol_mult=1.0, vol_sigma=0.0, channel="trade_quote", retrieved_on="2026-10-12",
             with_volume=False)
    smp = mk("SRC-SMP-01", all_combos, price_mult=1.0, price_sigma=0.04, vol_mult=1.0,
             vol_sigma=0.10, channel="sample", retrieved_on="2026-10-01",
             months_from="2024-10-01")

    write_csv(gov1, out_dir / "data/gov_landings.csv")
    write_csv(gov2, out_dir / "data/gov_aquaculture.csv")
    write_csv(ind, out_dir / "data/assoc_wholesale.csv")
    write_csv(trd, out_dir / "data/trade_price_notes.csv")
    write_csv(smp, out_dir / "data/sample_fallback.csv")

    registry = pd.DataFrame(SOURCES)
    write_csv(registry, out_dir / "registry/source_registry.csv")

    catalog = []
    for species, sp in SPECIES.items():
        regions = ";".join(sorted({r for s, r, _ in COMBOS if s == species}))
        catalog.append(dict(species=species, category=sp["category"],
                            source_type=sp["source_type"], regions=regions))
    write_csv(pd.DataFrame(catalog), out_dir / "registry/species_catalog.csv")

    files, manifest = planted_cases(gov1, gov2, ind, trd, registry)
    for rel, df in files.items():
        write_csv(df, out_dir / rel)
    (out_dir / "planted").mkdir(parents=True, exist_ok=True)
    (out_dir / "planted/planted_manifest.json").write_text(json.dumps(manifest, indent=2))

    primary = pd.concat([gov1, gov2], ignore_index=True)
    tests_dir = out_dir / "tests_only"
    tests_dir.mkdir(parents=True, exist_ok=True)
    gt = build_ground_truth(primary)
    (tests_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
    (tests_dir / "golden_cases.json").write_text(json.dumps(golden_cases(gt), indent=2))

    (out_dir / "README.md").write_text(README.format(as_of=AS_OF, seed=SEED))
    print("Wrote dataset to", out_dir)
    for name, df in [("gov_landings", gov1), ("gov_aquaculture", gov2), ("assoc_wholesale", ind),
                     ("trade_price_notes", trd), ("sample_fallback", smp)]:
        print(f"  {name}: {len(df)} rows")


if __name__ == "__main__":
    main()
