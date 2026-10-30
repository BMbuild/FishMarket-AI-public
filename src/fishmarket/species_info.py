"""Species background from GBIF (taxonomy, common names, occurrence points) and FishBase (biology).
Background only: none of this touches a price, number or verdict. Every call is optional and fails soft; failures are
reported, never hidden, and never cached. GBIF endpoints are the documented v1 species and occurrence routes.
The FishBase REST API (rOpenSci fishbaseapi) is documented but was not reachable from the build sandbox, so it is unverified."""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import validators

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data_real" / "species_cache.json"
CACHE_DAYS = 30
GBIF = "https://api.gbif.org/v1"
FISHBASE_BASES = [b for b in (os.environ.get("FISHBASE_API_URL"), "https://fishbase.ropensci.org",
                              "https://fishbase.ropensci.org/fishbase") if b]
MIN_CONFIDENCE = 90
MAX_POINTS = 300          # GBIF occurrence search page limit
UA = {"User-Agent": "fishmarket-ai-student-project"}


class SpeciesInfoError(Exception):
    pass


def http_get(url: str, params: dict | None = None, timeout: int = 12):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise SpeciesInfoError(f"{type(e).__name__}: {str(e)[:120]}") from None


def _binomial(name: str) -> str:
    return " ".join(str(name).split()).capitalize()


def gbif_lookup(name: str, get=http_get) -> dict:
    m = get(f"{GBIF}/species/match", {"name": name, "kingdom": "Animalia"})
    gate = validators.validate_gbif_match(m, MIN_CONFIDENCE)
    key, conf = m.get("usageKey"), m.get("confidence", 0)
    out = {"match_type": m.get("matchType"), "confidence": conf, "rank": m.get("rank"), "status": m.get("status"),
           "scientific_name": m.get("scientificName"), "family": m.get("family"), "order": m.get("order"), "key": key}
    out["gate"] = {"status": gate.status, "reason": gate.flag_reason}
    if gate.status == "FLAGGED":
        out["trusted"] = False
        out["note"] = "GBIF did not find a confident match, so no further GBIF facts are shown."
        return out
    out["trusted"] = True
    out["page"] = f"https://www.gbif.org/species/{key}"
    try:
        v = get(f"{GBIF}/species/{key}/vernacularNames", {"limit": 50})
        names = [x["vernacularName"] for x in v.get("results", []) if x.get("language") in ("eng", "en", None) and x.get("vernacularName")]
        out["common_names"] = list(dict.fromkeys(names))[:6]
    except SpeciesInfoError as e:
        out.setdefault("errors", []).append("common names: " + str(e))
    try:
        o = get(f"{GBIF}/occurrence/search", {"taxonKey": key, "hasCoordinate": "true", "country": "US", "limit": MAX_POINTS})
        pts, pstats = validators.clean_points(o.get("results", []))
        out["points_gate"] = pstats
        out["occurrence_count_us"] = o.get("count")
        out["points"] = pts
    except SpeciesInfoError as e:
        out.setdefault("errors", []).append("occurrences: " + str(e))
    return out


def fishbase_lookup(name: str, get=http_get, bases: list[str] | None = None) -> dict:
    genus, _, species = name.partition(" ")
    if not species.strip():
        return {"found": False, "note": "FishBase needs genus and species."}
    errors = []
    for base in bases or FISHBASE_BASES:
        try:
            r = get(f"{base.rstrip('/')}/species", {"genus": genus, "species": species.strip(), "limit": 1})
        except SpeciesInfoError as e:
            errors.append(f"{base}: {e}")
            continue
        gate = validators.validate_fishbase(r)
        if gate.status == "FLAGGED":
            errors.append(f"{base}: {gate.flag_reason}")
            continue
        rows = r.get("data") or []
        if not rows:
            return {"found": False, "base": base, "note": "Not in FishBase (it covers fish; crabs, lobsters and shellfish are in SeaLifeBase)."}
        row = rows[0]
        keep = ("SpecCode", "FBname", "Length", "CommonLength", "Weight", "Vulnerability", "DepthRangeShallow", "DepthRangeDeep",
                "Importance", "PriceCateg", "Aquaculture", "Fresh", "Brack", "Saltwater")
        return {"found": True, "base": base, "facts": {k: row[k] for k in keep if row.get(k) not in (None, "")}}
    return {"found": False, "errors": errors}


def _load_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def lookup(scientific_name: str, get=http_get, cache_path: Path = CACHE_PATH, now=time.time) -> dict:
    name = _binomial(scientific_name)
    cache = _load_cache(cache_path)
    hit = cache.get(name)
    if hit and now() - hit["fetched_at"] < CACHE_DAYS * 86400:
        return {**hit["data"], "from_cache": True}
    data = {"scientific_name": name, "errors": []}
    try:
        data["gbif"] = gbif_lookup(name, get)
    except SpeciesInfoError as e:
        data["gbif"] = None
        data["errors"].append("GBIF: " + str(e))
    data["fishbase"] = fishbase_lookup(name, get)
    if data["fishbase"].get("errors"):
        data["errors"].append("FishBase: " + "; ".join(data["fishbase"]["errors"]))
    if data["gbif"] is not None and not data["errors"]:    # only complete successes are cached
        try:
            cache_path.parent.mkdir(exist_ok=True)
            cache[name] = {"fetched_at": now(), "data": data}
            cache_path.write_text(json.dumps(cache))
        except OSError:
            pass
    return {**data, "from_cache": False}
