"""Look up species facts from GBIF (taxonomy, occurrence count). FishBase is OFF by default: rOpenSci says the old
REST API was replaced by parquet tables, so set FISHBASE_API_URL only if you have a working REST endpoint.
Usage: python scripts/fetch_species_info.py "Gadus morhua" ["Homarus americanus" ...]  -> data_real/species_info.json
Each service is tried separately; a failure is recorded, never hidden."""
import json, pathlib, sys
from _net import get_json

GBIF = "https://api.gbif.org/v1"
import os
FISHBASE = os.environ.get("FISHBASE_API_URL")   # no default on purpose
out = pathlib.Path(__file__).resolve().parents[1] / "data_real" / "species_info.json"
res = {}
for name in sys.argv[1:] or ["Gadus morhua"]:
    genus, _, sp = name.partition(" ")
    rec = {"scientific_name": name}
    try:
        m = get_json(f"{GBIF}/species/match", {"name": name})
        rec["gbif"] = {k: m.get(k) for k in ("usageKey", "scientificName", "rank", "status", "confidence", "family", "order")}
        o = get_json(f"{GBIF}/occurrence/search", {"scientificName": name, "limit": 0})
        rec["gbif"]["occurrence_count"] = o.get("count")
    except SystemExit as e:
        rec["gbif_error"] = str(e)
    if not FISHBASE:
        rec["fishbase_skipped"] = "no FISHBASE_API_URL set (old REST API retired; parquet source not wired yet)"
    else:
      try:
        f = get_json(f"{FISHBASE}/species", {"genus": genus, "species": sp, "limit": 1})
        rec["fishbase"] = (f.get("data") or [None])[0]
      except SystemExit as e:
        rec["fishbase_error"] = str(e)
    res[name] = rec
out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(res, indent=2, default=str))
print(f"{len(res)} species -> {out}")
