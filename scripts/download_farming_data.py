"""One-time download of the two small farming datasets the app reads locally. Run from the project folder:
    python scripts/download_farming_data.py
Writes data_real/oecd/aquaculture_production.csv and data_real/fishwatch/species.json, then prints a short summary.
Re-run it whenever you want fresher data. TLS is verified; no keys are needed."""
import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fishmarket import live  # noqa: E402

UA = {"User-Agent": live.UA, "Accept": "*/*"}


def get(url: str, timeout: int = 180) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def main() -> int:
    ok = True
    # OECD: look up the agency from OECD's own metadata, then take the whole dataflow as CSV with labels
    try:
        st = live.oecd_structure()
        url = f"{live.OECD}/data/{st['agency']},{live.OECD_FLOW},/all?format=csvfilewithlabels"
        body = get(url).decode("utf-8", "replace")
        rows = list(csv.DictReader(io.StringIO(body)))
        if not rows or not {"OBS_VALUE", "TIME_PERIOD", "REF_AREA", "SPECIES"} <= set(rows[0]):
            raise RuntimeError("unexpected CSV columns: " + ", ".join(list(rows[0])[:12] if rows else ["(empty)"]))
        live.LOCAL_OECD.parent.mkdir(parents=True, exist_ok=True)
        live.LOCAL_OECD.write_text(body, encoding="utf-8")
        yrs = sorted({r["TIME_PERIOD"][:4] for r in rows})
        print(f"OK   OECD aquaculture: {len(rows):,} rows, {len({r['REF_AREA'] for r in rows})} countries, "
              f"{len({r['SPECIES'] for r in rows})} species, {yrs[0]}-{yrs[-1]}, {len(body)/1e6:.1f} MB -> {live.LOCAL_OECD}")
        us = [r for r in rows if r["REF_AREA"] == "USA" and "salmo salar" in str(list(r.values())).lower()]
        print(f"     U.S. Atlantic salmon rows: {len(us)}")
        from fishmarket import oecd_clean
        rep = oecd_clean.run()
        print(f"OK   OECD cleansing gate: {rep['status']}; flags {rep['flags']} -> {oecd_clean.CLEAN}")
    except Exception as e:
        ok = False
        print(f"FAIL OECD aquaculture: {type(e).__name__}: {e}")
    # FishWatch: the API was retired (it now redirects to https://www.fisheries.noaa.gov/topic/sustainable-seafood).
    # Farming-method answers come from the sourced farming entries in data_real/wiki/wiki.md instead.
    print("SKIP FishWatch: NOAA retired the FishWatch API; farming answers use the mini-wiki's farming entries.")
    if "--fishwatch" not in sys.argv:
        return 0 if ok else 1
    try:
        req = urllib.request.Request(live.FISHWATCH, headers={**UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            body, final, ctype = r.read(), r.geturl(), r.headers.get("Content-Type", "")
        try:
            data = json.loads(body)
        except ValueError:
            snippet = body[:200].decode("utf-8", "replace").replace("\n", " ")
            raise RuntimeError(f"not JSON (content-type {ctype!r}, final URL {final}). Start of response: {snippet!r}") from None
        if not isinstance(data, list) or not data or "Species Name" not in data[0]:
            raise RuntimeError("response was not a list of species records")
        live.LOCAL_FISHWATCH.parent.mkdir(parents=True, exist_ok=True)
        live.LOCAL_FISHWATCH.write_text(json.dumps(data), encoding="utf-8")
        farmed = [d["Species Name"] for d in data if "farm" in (str(d.get("Harvest Type", "")) + str(d.get("Species Name", ""))).lower()]
        print(f"OK   FishWatch: {len(data)} species, {len(farmed)} farmed, {len(body)/1e6:.1f} MB -> {live.LOCAL_FISHWATCH}")
        print("     farmed examples:", ", ".join(live._plain(x) for x in farmed[:8]))
    except Exception as e:
        ok = False
        print(f"FAIL FishWatch: {type(e).__name__}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
