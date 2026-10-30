"""Builds data_real/crosswalk/scenario_noaa_species.csv: the real species landed commercially in each scenario
region, from NOAA landings (last 5 years), with the real price level and landed volume used to anchor generated
scenario series. Run after the NOAA file changes:  python tools/make_scenario_species.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fishmarket import real_data  # noqa: E402

OUT = ROOT / "data_real" / "crosswalk" / "scenario_noaa_species.csv"
MIN_POUNDS_5Y = 100_000
MIN_VALUE_5Y = 200_000
GENERIC = {"crustaceans", "finfishes", "shellfish", "mollusks", "molluscs", "marine fishes", "groundfishes", "fishes", "invertebrates"}
SKIP = ("(", "unclassified", "bait", " fw ", "fw ", "brine", "fiddler", "hermit", "cleaner", "ghost", "mud shrimp", "ornamental")


def main() -> None:
    with open(ROOT / "data_real" / "crosswalk" / "scenario_regions.csv", newline="", encoding="utf-8") as f:
        regions = {r["noaa_region"]: r["scenario_region"] for r in csv.DictReader(f)}
    with open(ROOT / "data_real" / "crosswalk" / "scenario_species.csv", newline="", encoding="utf-8") as f:
        taken = set()      # (noaa name, scenario region or "*"): real series already behind a hand-made scenario species
        for r in csv.DictReader(f):
            for n in r["noaa_species"].split(";"):
                if n.strip():
                    name, _, reg = n.partition("@")
                    taken.add((name.strip().lower(), reg.strip() or "*"))
    df = real_data.load().df
    df = df[df["region"].isin(regions)]
    last = df.groupby("region")["year"].transform("max")        # each region's own latest 5 years (Great Lakes reporting ends earlier)
    d = df[df["year"] > last - 5]
    g = d.groupby(["region", "species"]).agg(pounds=("pounds", "sum"), dollars=("dollars", "sum")).reset_index()
    g = g[(g["pounds"] >= MIN_POUNDS_5Y) & (g["dollars"] >= MIN_VALUE_5Y)]
    rows = []
    for _, r in g.iterrows():
        name = str(r["species"])
        low = f" {name.lower()} "
        sreg = regions[r["region"]]
        if any(s in low for s in SKIP) or name.lower() in GENERIC or (name.lower(), "*") in taken or (name.lower(), sreg) in taken:
            continue
        s = d[(d["region"] == r["region"]) & (d["species"] == name)].sort_values("year")
        s = s[s["pounds"] > 0]
        first, end = s.iloc[0], s.iloc[-1]
        yrs = int(end["year"] - first["year"])
        trend = ((end["price"] / first["price"]) ** (1 / yrs) - 1) if yrs >= 2 and first["price"] > 0 else 0.0
        rows.append({"scenario_region": regions[r["region"]], "species": name, "last_year": int(end["year"]),
                     "price_usd_per_lb": round(float(end["price"]), 2), "monthly_lb": int(end["pounds"] / 12),
                     "value_5y_usd": int(r["dollars"]), "price_trend": round(max(-0.05, min(0.05, float(trend))), 4)})
    rows.sort(key=lambda x: (x["scenario_region"], -x["value_5y_usd"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} species-region rows written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
