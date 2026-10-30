"""Collection -> validation gate -> analysis handoff, run from the command line.
Usage:  python fishmarket_pipeline.py [noaa_landings_full.csv] [--species "American lobster"] [--no-api]

What it does
1. Classifies every NOAA row (VALID / REVIEW / REJECTED / EXCLUDED_BY_DESIGN) with reason codes.
2. Writes data_clean/noaa_rejected.csv, data_clean/noaa_review.csv and data_clean/validation_report.json.
3. Looks up one species in GBIF and FishBase using its SCIENTIFIC name from the NOAA file (not the common name).
Network calls fail soft and keep TLS verification on."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from fishmarket import cleansing, real_data, species_info  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default=str(real_data.DEFAULT_CSV))
    ap.add_argument("--species", help="clean name, e.g. 'American lobster' (default: biggest by value)")
    ap.add_argument("--no-api", action="store_true")
    a = ap.parse_args()

    raw = pd.read_csv(a.csv, low_memory=False)
    cls = cleansing.classify(raw)
    rep = cleansing.write_outputs(cls, ROOT / "data_clean")
    print(f"Rows read: {rep['total_rows']:,}")
    for k, v in rep["by_status"].items():
        print(f"  {k:<20} {v:>9,}")
    print(f"Pass rate, all rows: {rep['pass_rate_all_rows']:.1%}")
    print(f"Pass rate, rows that should have prices or weights: {rep['pass_rate_in_scope']:.1%}")
    print("Reasons:")
    for k, v in rep["reason_counts"].items():
        print(f"  {k:<34} {v:>8,}")
    print("Wrote data_clean/noaa_rejected.csv, noaa_review.csv, validation_report.json")
    if a.no_api:
        return 0

    L = real_data.load(a.csv)
    top = real_data.top_species(L.df)
    sp = a.species or top.iloc[0]["species"]
    sci = L.df.loc[L.df["species"] == sp, "scientific"].dropna()
    if sci.empty:
        print(f"No scientific name in the NOAA file for {sp}; skipping GBIF and FishBase.")
        return 0
    print(f"\nLooking up {sp} as '{sci.iloc[0].strip()}'")
    info = species_info.lookup(sci.iloc[0])
    print("GBIF:", (info.get("gbif") or {}).get("gate") or "no result")
    print("FishBase:", info["fishbase"].get("note") or ("found" if info["fishbase"].get("found") else "not found"))
    for e in info["errors"]:
        print("  error:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
