"""Download NOAA FOSS foreign trade data (paginated, same ODS REST pattern as the landings script).
Usage: python scripts/fetch_noaa_trade.py [--max-pages 200]  -> data_real/noaa_trade.csv
Run on a machine that can reach apps-st.fisheries.noaa.gov. Field names are taken from the response, not assumed."""
import argparse, csv, pathlib
from _net import get_json

BASE = "https://apps-st.fisheries.noaa.gov/ods/foss/trade_data/"
ap = argparse.ArgumentParser(); ap.add_argument("--max-pages", type=int, default=200); a = ap.parse_args()
out = pathlib.Path(__file__).resolve().parents[1] / "data_real" / "noaa_trade.csv"
rows, offset = [], 0
for _ in range(a.max_pages):
    d = get_json(BASE, {"limit": 1000, "offset": offset})
    items = d.get("items", [])
    rows += items
    if not d.get("hasMore") or not items:
        break
    offset += len(items)
if not rows:
    raise SystemExit("No rows returned.")
cols = sorted({k for r in rows for k in r if k != "links"})
out.parent.mkdir(exist_ok=True)
with out.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
print(f"{len(rows)} rows -> {out}")
