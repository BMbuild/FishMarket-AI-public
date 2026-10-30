"""Free live API adapters. Nothing is bulk-downloaded: each question makes a few small calls, cached on disk.

  * OBIS (https://api.obis.org/v3): no key. Occurrence counts by decade plus one small recent sample.
  * OECD Data Explorer SDMX API (https://sdmx.oecd.org/public/rest): no key. Aquaculture production by country and species.
  * NOAA FishWatch API (https://www.fishwatch.gov/api/species): no key. Farming methods, feeds and production text for farmed species.
  * U.S. Census international trade API: free key in CENSUS_API_KEY (https://api.census.gov/data/key_signup.html).
    NOAA's own trade tool has no API, and Census is the upstream source of U.S. seafood trade statistics.

Off by default. Turn on with FISHMARKET_LIVE=1 (or `--live` on the CLI). Every failure raises LiveError; callers turn that
into a refusal or a labelled fallback, never a guess. TLS is always verified. `python -m fishmarket.live check` makes a few
tiny real calls and reports whether the response shapes still match what this code expects."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = Path(os.environ.get("FISHMARKET_LIVE_CACHE", ROOT / "cache" / "live"))
OBIS = "https://api.obis.org/v3"
CENSUS = "https://api.census.gov/data/timeseries/intltrade"
OECD = "https://sdmx.oecd.org/public/rest"
OECD_FLOW = "DSD_FISH_PROD@DF_FISH_AQUA"          # aquaculture production; agency is looked up, not assumed
FISHWATCH = "https://www.fishwatch.gov/api/species"
# Local snapshots (made once by `python scripts/download_farming_data.py`); used instead of live calls when present
LOCAL_OECD = ROOT / "data_real" / "oecd" / "aquaculture_production.csv"
LOCAL_OECD_CLEAN = ROOT / "data_real" / "oecd" / "aquaculture_clean.csv"      # written by `python -m fishmarket.oecd_clean`
LOCAL_FISHWATCH = ROOT / "data_real" / "fishwatch" / "species.json"
TTL_DAYS = 14
MAX_BYTES = 20_000_000
TIMEOUT = 25
UA = "fishmarket-ai/1.0 (student project; free public APIs only)"
# HS4 headings of chapter 03 (fish, crustaceans, molluscs)
HS4 = {"0302": "fresh or chilled fish", "0303": "frozen fish", "0304": "fish fillets and other fish meat", "0305": "dried, salted or smoked fish",
       "0306": "crustaceans (lobster, crab, shrimp)", "0307": "molluscs (scallops, oysters, clams, squid)"}


class LiveError(Exception):
    pass


def _dotenv(name: str) -> str:
    """Reads one value from the project's .env (gitignored) without printing or exporting anything else."""
    try:
        raw = (ROOT / ".env").read_bytes()
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", "replace")
        for ln in text.splitlines():
            k, _, v = ln.strip().partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def enabled() -> bool:
    return (os.environ.get("FISHMARKET_LIVE") or _dotenv("FISHMARKET_LIVE")).strip().lower() in ("1", "true", "yes")


def _default_fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:          # default SSL context: certificates are verified
            body = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise LiveError(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}") from None
    except Exception as e:                                                # offline, blocked, DNS, timeout
        raise LiveError(f"could not reach {urllib.parse.urlsplit(url).netloc} ({type(e).__name__})") from None
    if len(body) > MAX_BYTES:
        raise LiveError("response larger than the 20 MB safety cap")
    return body.decode("utf-8", "replace")


def get_text(base: str, params: dict, *, secret: tuple[str, ...] = ("key",), fetch=None, cache_dir: Path | None = None, ttl_days: int = TTL_DAYS) -> str:
    """GET base?params as text, cached. The cache key ignores secret params, and secrets are never logged or stored."""
    q = {k: v for k, v in params.items() if v is not None}
    pub = {k: v for k, v in q.items() if k not in secret}
    url = f"{base}?{urllib.parse.urlencode(q)}" if q else base
    cdir = cache_dir or CACHE_DIR
    path = cdir / (hashlib.sha256(f"{base}?{urllib.parse.urlencode(sorted(pub.items()))}".encode()).hexdigest() + ".txt")
    try:
        if path.exists() and time.time() - path.stat().st_mtime < ttl_days * 86400:
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    text = (fetch or _default_fetch)(url)
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except Exception:
        pass
    return text


def get_json(base: str, params: dict, *, secret: tuple[str, ...] = ("key",), fetch=None, cache_dir: Path | None = None, ttl_days: int = TTL_DAYS):
    """GET base?params and parse JSON. The cache key ignores secret params, and secrets are never logged or stored."""
    q = {k: v for k, v in params.items() if v is not None}
    pub = {k: v for k, v in q.items() if k not in secret}
    url = f"{base}?{urllib.parse.urlencode(q)}"
    cdir = cache_dir or CACHE_DIR
    path = cdir / (hashlib.sha256(f"{base}?{urllib.parse.urlencode(sorted(pub.items()))}".encode()).hexdigest() + ".json")
    try:
        if path.exists() and time.time() - path.stat().st_mtime < ttl_days * 86400:
            return json.loads(path.read_text())
    except Exception:
        pass
    text = (fetch or _default_fetch)(url)
    try:
        data = json.loads(text)
    except Exception:
        raise LiveError("response was not JSON") from None
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except Exception:
        pass                                                              # caching is best effort
    return data


# ------------------------------------------------------------------ OBIS
def obis_count(name: str, start: str | None = None, end: str | None = None, **kw) -> int:
    """Number of OBIS occurrence records for a scientific name (one call, size=1)."""
    d = get_json(f"{OBIS}/occurrence", {"scientificname": name, "size": 1, "startdate": start, "enddate": end}, **kw)
    if not isinstance(d, dict) or not isinstance(d.get("total"), int):
        raise LiveError("OBIS response had no integer 'total' (shape changed?)")
    return d["total"]


def obis_sample(name: str, start: str | None = None, end: str | None = None, size: int = 500, **kw) -> list[dict]:
    """A small sample of OBIS records (size capped at 1000)."""
    d = get_json(f"{OBIS}/occurrence", {"scientificname": name, "size": min(int(size), 1000), "startdate": start, "enddate": end}, **kw)
    if not isinstance(d, dict) or not isinstance(d.get("results"), list):
        raise LiveError("OBIS response had no 'results' list (shape changed?)")
    return d["results"]


def _month(rec: dict):
    v = rec.get("month")
    if v is None and isinstance(rec.get("eventDate"), str) and len(rec["eventDate"]) >= 7 and rec["eventDate"][4] == "-":
        v = rec["eventDate"][5:7]
    try:
        m = int(v)
        return m if 1 <= m <= 12 else None
    except (TypeError, ValueError):
        return None


def obis_profile(name: str, last_year: int, decades: int = 6, **kw) -> dict:
    """Counts per decade and a recent sample summary for one species. All numbers come straight from OBIS responses."""
    first = (last_year // 10) * 10 - 10 * (decades - 1)
    by_decade = {}
    for d0 in range(first, last_year + 1, 10):
        by_decade[d0] = obis_count(name, f"{d0}-01-01", f"{min(d0 + 9, last_year)}-12-31", **kw)
    total = obis_count(name, **kw)
    sample = obis_sample(name, f"{last_year - 9}-01-01", f"{last_year}-12-31", **kw)
    pts = [(r["decimalLatitude"], r["decimalLongitude"]) for r in sample if isinstance(r.get("decimalLatitude"), (int, float)) and isinstance(r.get("decimalLongitude"), (int, float))]
    months = [m for m in (_month(r) for r in sample) if m]
    out = {"name": name, "total": total, "by_decade": by_decade, "sample_n": len(sample), "sample_points": len(pts), "months": sorted(set(months)), "month_counts": {m: months.count(m) for m in sorted(set(months))}}
    if pts:
        lats, lons = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
        out["lat_range"] = (lats[len(lats) // 20], lats[-1 - len(lats) // 20])      # 5th to 95th percentile of the sample
        out["lon_range"] = (lons[len(lons) // 20], lons[-1 - len(lons) // 20])
    return out


# ------------------------------------------------------------------ Census trade
def _key(key: str | None) -> str:
    k = key or os.environ.get("CENSUS_API_KEY") or _dotenv("CENSUS_API_KEY")
    if not k:
        raise LiveError("a free Census API key is needed (set CENSUS_API_KEY; sign up at https://api.census.gov/data/key_signup.html)")
    return k


def trade_by_country(flow: str, hs4: str, year: int, key: str | None = None, **kw) -> dict:
    """Annual U.S. seafood trade value (US dollars) for one HS4 heading, total and by partner country (year-to-date at December)."""
    if hs4 not in HS4:
        raise LiveError(f"unsupported HS4 heading {hs4}")
    imp = flow == "imports"
    if flow not in ("imports", "exports"):
        raise LiveError("flow must be imports or exports")
    com, val = ("I_COMMODITY", "GEN_VAL_YR") if imp else ("E_COMMODITY", "ALL_VAL_YR")
    rows = get_json(f"{CENSUS}/{flow}/hs", {"get": f"{com},CTY_CODE,CTY_NAME,{val}", "YEAR": year, "MONTH": "12", "COMM_LVL": "HS4", com: hs4, "key": _key(key)}, **kw)
    if not (isinstance(rows, list) and len(rows) >= 2 and isinstance(rows[0], list)):
        raise LiveError("Census response was not a header row plus data rows (shape changed or empty)")
    head = rows[0]
    try:
        ic, in_, iv = head.index("CTY_CODE"), head.index("CTY_NAME"), head.index(val)
    except ValueError:
        raise LiveError("Census response is missing expected columns") from None
    partners, total = [], None
    for r in rows[1:]:
        try:
            v = float(r[iv])
        except (TypeError, ValueError):
            continue
        code = str(r[ic]).strip()
        if code == "-" or str(r[in_]).upper().startswith("TOTAL"):
            total = v                                              # Census's own all-countries total
        elif code.isdigit() and not code.startswith("00"):         # real countries only: groups are 00nn (APEC, OECD...) or nXXX (ASIA...)
            partners.append((str(r[in_]).title(), v))
    if not partners:
        raise LiveError("Census returned no partner rows for that heading and year")
    partners.sort(key=lambda t: -t[1])
    if total is None:
        total = sum(v for _, v in partners)
    return {"flow": flow, "hs4": hs4, "label": HS4[hs4], "year": year, "total_usd": total, "top": partners[:5], "n_partners": len(partners)}


# ------------------------------------------------------------------ OECD aquaculture (SDMX)
import csv as _csv
import io as _io
import re as _re
import xml.etree.ElementTree as _ET

COUNTRIES = {"united states": "USA", "us": "USA", "u.s.": "USA", "usa": "USA", "america": "USA", "canada": "CAN", "norway": "NOR",
             "chile": "CHL", "united kingdom": "GBR", "uk": "GBR", "scotland": "GBR", "japan": "JPN", "korea": "KOR", "south korea": "KOR",
             "spain": "ESP", "france": "FRA", "italy": "ITA", "greece": "GRC", "turkey": "TUR", "turkiye": "TUR", "mexico": "MEX",
             "australia": "AUS", "new zealand": "NZL", "iceland": "ISL", "ireland": "IRL", "denmark": "DNK", "germany": "DEU",
             "netherlands": "NLD", "portugal": "PRT", "colombia": "COL", "costa rica": "CRI", "israel": "ISR", "poland": "POL"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def oecd_structure(**kw) -> dict:
    """Agency and dimension order of the aquaculture dataflow, read from OECD's own structure metadata."""
    xml = get_text(f"{OECD}/dataflow/all/{OECD_FLOW}/latest", {"references": "datastructure"}, ttl_days=60, **kw)
    try:
        root = _ET.fromstring(xml)
    except _ET.ParseError:
        raise LiveError("OECD structure response was not XML (shape changed?)") from None
    agency, dims = None, []
    for el in root.iter():
        t = _local(el.tag)
        if t == "Dataflow" and el.get("id") == OECD_FLOW:
            agency = el.get("agencyID")
        elif t == "Dimension" and el.get("id"):
            dims.append((int(el.get("position") or len(dims) + 1), el.get("id")))
    if not agency or not dims:
        raise LiveError("OECD structure had no agency or dimensions for the aquaculture dataflow")
    return {"agency": agency, "dims": [d for _, d in sorted(dims)]}


_LOCAL_CACHE: dict = {}


def _local_file() -> Path:
    """The cleaned file when it exists and is newer than the raw download, else the raw download."""
    if LOCAL_OECD_CLEAN.exists() and (not LOCAL_OECD.exists() or LOCAL_OECD_CLEAN.stat().st_mtime >= LOCAL_OECD.stat().st_mtime):
        return LOCAL_OECD_CLEAN
    return LOCAL_OECD


def _local_all() -> list[dict]:
    src = _local_file()
    key = (str(src), src.stat().st_mtime)
    if key not in _LOCAL_CACHE:
        with open(src, encoding="utf-8", newline="") as f:
            _LOCAL_CACHE.clear()
            _LOCAL_CACHE[key] = [r for r in _csv.DictReader(f) if r.get("OBS_VALUE") not in (None, "")]
    return _LOCAL_CACHE[key]


def _local_oecd_rows(filters: dict, start: int) -> list[dict]:
    rows = _local_all()
    if rows and not {"OBS_VALUE", "TIME_PERIOD"} <= set(rows[0]):
        raise LiveError("local OECD file is missing OBS_VALUE or TIME_PERIOD; re-run scripts/download_farming_data.py")
    out = []
    for r in rows:
        if any(r.get(d) not in vals for d, vals in filters.items()):
            continue
        try:
            if int(str(r["TIME_PERIOD"])[:4]) < start:
                continue
        except ValueError:
            continue
        out.append(r)
    return out


def farming_available() -> dict:
    return {"oecd": LOCAL_OECD.exists() or LOCAL_OECD_CLEAN.exists(), "fishwatch": LOCAL_FISHWATCH.exists()}


def _oecd_rows(filters: dict, start: int, **kw) -> list[dict]:
    if (LOCAL_OECD.exists() or LOCAL_OECD_CLEAN.exists()) and not kw.get("fetch"):
        return _local_oecd_rows(filters, start)
    st = oecd_structure(**kw)
    key = ".".join("+".join(filters[d]) if d in filters else "" for d in st["dims"])
    text = get_text(f"{OECD}/data/{st['agency']},{OECD_FLOW},/{key}", {"startPeriod": start, "format": "csvfilewithlabels"}, **kw)
    if text.lstrip().startswith("<") or not text.strip():
        raise LiveError("OECD returned no CSV data for that query")
    rows = list(_csv.DictReader(_io.StringIO(text)))
    if rows and not {"OBS_VALUE", "TIME_PERIOD"} <= set(rows[0]):
        raise LiveError("OECD CSV is missing OBS_VALUE or TIME_PERIOD (shape changed?)")
    return rows


def _label(row: dict, code_col: str) -> str:
    """csvfilewithlabels puts the label in the column right after the code column."""
    keys = list(row)
    i = keys.index(code_col) if code_col in keys else -1
    return row[keys[i + 1]] if 0 <= i < len(keys) - 1 else row.get(code_col, "")


def aquaculture(scientific: str, country: str = "USA", start: int = 2005, **kw) -> dict:
    """Farmed production for one species (matched by the scientific name in OECD's species label) in one country,
    plus that species' latest-year ranking across the countries OECD reports."""
    rows = _oecd_rows({"REF_AREA": [country]}, start, **kw)
    sci = scientific.strip().lower()
    mine = [r for r in rows if sci and f"[{sci}" in _label(r, "SPECIES").lower()]
    if not mine:
        genus = sci.split()[0] if sci else ""
        mine = [r for r in rows if genus and f"[{genus}" in _label(r, "SPECIES").lower()]
        match = "genus" if mine else "none"
    else:
        match = "species"
    if not mine:
        return {"country": country, "match": "none", "species_seen": sorted({_label(r, "SPECIES") for r in rows})[:40]}
    code, sp_label = mine[0].get("SPECIES", ""), _label(mine[0], "SPECIES")
    mine = [r for r in mine if r.get("SPECIES") == code]
    series, imputed, dropped, gate_flags = {}, set(), 0, {}
    for r in mine:
        try:
            v = float(r["OBS_VALUE"])
        except (TypeError, ValueError):
            continue
        if v < 0 or v != v:                       # validation: negative or NaN production is impossible; drop and count it
            dropped += 1
            continue
        unit = r.get("UNIT_MEASURE", "")
        mult = int(r.get("UNIT_MULT") or 0) if str(r.get("UNIT_MULT") or "0").lstrip("-").isdigit() else 0
        y = int(str(r["TIME_PERIOD"])[:4])
        series.setdefault(unit, {})[y] = v * 10 ** mult
        if r.get("OBS_STATUS") == "I":
            imputed.add((unit, y))
        if r.get("FLAGS"):
            gate_flags[f"{unit}:{y}"] = r["FLAGS"].split("|")
    if not series:
        return {"country": country, "match": "none", "species_seen": []}
    out = {"country": country, "match": match, "species_code": code, "species_label": sp_label, "series": series,
           "units": {u: next((_label(r, "UNIT_MEASURE") for r in mine if r.get("UNIT_MEASURE") == u), u) for u in series}, "imputed": sorted(imputed),
           "dropped_invalid": dropped, "gate_flags": gate_flags, "cleaned": bool(mine and "STATUS" in mine[0])}
    try:
        allc = _oecd_rows({"SPECIES": [code]}, start, **kw) if code else []
        unit = "T" if "T" in series else next(iter(series))
        ranks = {}
        for r in allc:
            if r.get("UNIT_MEASURE") != unit:
                continue
            try:
                ranks.setdefault(int(str(r["TIME_PERIOD"])[:4]), []).append((_label(r, "REF_AREA") or r.get("REF_AREA", ""), r.get("REF_AREA", ""), float(r["OBS_VALUE"])))
            except (TypeError, ValueError, KeyError):
                continue
        if ranks:
            y = max(ranks)
            top = sorted(ranks[y], key=lambda t: -t[2])
            out["rank_year"], out["rank_unit"], out["top_countries"] = y, unit, [(n, v) for n, _, v in top[:5]]
            codes = [c for _, c, _ in top]
            out["rank"] = codes.index(country) + 1 if country in codes else None
            out["n_countries"] = len(top)
    except LiveError:
        pass                                                  # the ranking is a bonus; the country series stands alone
    return out


# ------------------------------------------------------------------ NOAA FishWatch
FIELDS = ("Farming Methods", "Feeds", "Production", "Environmental Effects", "Disease Treatment and Prevention", "Harvest Type", "Location")


def _plain(html) -> str:
    t = _re.sub(r"<[^>]+>", " ", str(html or ""))
    t = _re.sub(r"&nbsp;|&#160;", " ", t)
    t = _re.sub(r"&amp;", "&", t)
    t = _re.sub(r"&[a-z#0-9]+;", "", t)
    return _re.sub(r"\s+", " ", t).strip()


def fishwatch_list(**kw) -> list[dict]:
    if LOCAL_FISHWATCH.exists() and not kw.get("fetch"):
        d = json.loads(LOCAL_FISHWATCH.read_text(encoding="utf-8"))
    else:
        d = get_json(FISHWATCH, {}, **kw)
    if not isinstance(d, list) or not d or not isinstance(d[0], dict) or "Species Name" not in d[0]:
        raise LiveError("FishWatch response was not a list of species records (API retired or shape changed?)")
    return d


def fishwatch_farmed(name: str, scientific: str = "", **kw) -> dict | None:
    """The FishWatch record for a species, preferring a farmed profile. Matched by scientific name, then common name."""
    recs = fishwatch_list(**kw)
    sci, nm = scientific.strip().lower(), name.strip().lower()

    def score(r):
        rs, rn = _plain(r.get("Scientific Name")).lower(), _plain(r.get("Species Name")).lower()
        farmed = "farm" in (_plain(r.get("Harvest Type")) + rn).lower()
        hit = 3 if sci and rs == sci else 2 if nm and nm in rn else 0
        return (hit, farmed)
    best = max(recs, key=score)
    if score(best)[0] == 0:
        return None
    out = {"name": _plain(best.get("Species Name")), "scientific": _plain(best.get("Scientific Name")), "path": best.get("Path", ""),
           "updated": _plain(best.get("last_update"))}
    for f in FIELDS:
        v = _plain(best.get(f) or best.get(f.replace(" ", "_")) or best.get(f + "_"))
        if v:
            out[f] = v
    return out


def check() -> int:
    """Tiny real calls to confirm the APIs still answer in the shape this code expects."""
    ok = True
    for label, fn in (("OBIS count (Homarus americanus)", lambda: obis_count("Homarus americanus")),
                      ("OBIS sample", lambda: len(obis_sample("Homarus americanus", size=5))),
                      ("Census imports 0306", lambda: trade_by_country("imports", "0306", 2023)["total_usd"]),
                      ("Census exports 0306", lambda: trade_by_country("exports", "0306", 2023)["total_usd"]),
                      ("OECD structure", lambda: oecd_structure()),
                      ("OECD aquaculture (Atlantic salmon, Norway)", lambda: {k: v for k, v in aquaculture("Salmo salar", "NOR").items() if k != "series"}),
                      ("FishWatch list", lambda: len(fishwatch_list())),
                      ("FishWatch farmed Atlantic salmon", lambda: (fishwatch_farmed("Atlantic salmon", "Salmo salar") or {}).get("name"))):
        try:
            print(f"OK    {label}: {str(fn())[:300]}")
        except LiveError as e:
            ok = False
            print(f"FAIL  {label}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    if (sys.argv[1:] or ["check"])[0] == "check":
        sys.exit(check())
