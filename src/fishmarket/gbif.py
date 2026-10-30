"""GBIF occurrence ingestion: format inspection, a row-level validation gate, and a chunked build of small 'gold' tables.

Why chunked pandas and not one big load: a GBIF download can be several GB. Each chunk is classified, valid rows are reduced to
mergeable aggregates (counts per taxon x grid cell x year, month histograms, centroid sums), and only those aggregates are kept.
Memory stays bounded; the aggregates are small. Pure pandas, so it runs without DuckDB or pyarrow (pyarrow is only needed to read
Parquet input).

GBIF records are observations, not abundance or catch. Nothing here turns counts into stock size.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LAKE = Path(os.environ.get("FISHMARKET_LAKE", ROOT / "lake"))
BOXES_PATH = ROOT / "data_real" / "crosswalk" / "region_boxes.csv"

GRID_DEG = 0.25
MAX_UNCERTAINTY_M = 10_000
OLD_SPECIMEN_YEAR = 1900
MIN_YEAR, MAX_YEAR = 1700, 2100          # MAX is a sanity cap; the gate does not read the clock
POINTS_PER_TAXON = 1500
REQUIRED = ["taxonKey", "decimalLatitude", "decimalLongitude", "year", "basisOfRecord", "occurrenceStatus"]
OPTIONAL = ["gbifID", "speciesKey", "scientificName", "species", "genus", "family", "order", "class", "month", "eventDate",
            "coordinateUncertaintyInMeters", "individualCount", "countryCode", "stateProvince", "issue", "datasetKey", "license",
            "establishmentMeans"]
BAD_ISSUES = ("ZERO_COORDINATE", "COORDINATE_OUT_OF_RANGE", "COUNTRY_COORDINATE_MISMATCH", "PRESUMED_SWAPPED_COORDINATE",
              "PRESUMED_NEGATED_LATITUDE", "PRESUMED_NEGATED_LONGITUDE")
NC_LICENSE = "CC_BY_NC_4_0"


class GbifFormatError(ValueError):
    pass


# ------------------------------------------------------------------ inspect
def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")


def detect_format(path: Path) -> dict:
    """Identify what was downloaded. Returns {format, table_path/zip member, sep}."""
    path = Path(path)
    if path.is_dir():
        per_species = sorted(path.glob("gbif_*.csv"))
        if per_species and not any((path / n).exists() for n in ("occurrence.txt", "occurrence.csv", "occurrence.tsv")):
            # a folder of per-species exports from the GBIF occurrence search API (scripts/download_external_datasets.py)
            return {"format": "api_csv_dir", "file": str(path), "files": [str(f) for f in per_species], "sep": ","}
        for name in ("occurrence.txt", "occurrence.csv", "occurrence.tsv"):
            if (path / name).exists():
                return {"format": "dwca_dir", "file": str(path / name), "sep": "\t"}
        pq = sorted(path.glob("**/*.parquet"))
        if pq:
            return {"format": "parquet", "file": str(path), "sep": None}
        raise GbifFormatError(f"No occurrence table found in {path}")
    low = path.name.lower()
    if low.endswith(".parquet"):
        return {"format": "parquet", "file": str(path), "sep": None}
    if low.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        member = next((n for n in names if n.endswith(("occurrence.txt", ".csv", ".tsv"))), None)
        if not member:
            raise GbifFormatError(f"No occurrence table inside {path.name}: {names[:5]}")
        return {"format": "dwca_zip" if member.endswith("occurrence.txt") else "simple_csv_zip", "file": str(path), "member": member, "sep": "\t"}
    with _open_text(path) as f:
        head = f.readline()
    sep = "\t" if head.count("\t") >= head.count(",") else ","
    return {"format": "simple_csv" if sep == "\t" else "csv", "file": str(path), "sep": sep}


LICENSE_CODES = {"by-nc": "CC_BY_NC_4_0", "/by/": "CC_BY_4_0", "zero": "CC0_1_0"}
SKIPPED_FILES: list[str] = []          # per-species files that could not be read in the last api_csv_dir pass


def _license_code(v: str) -> str:
    low = str(v).lower()
    return next((code for k, code in LICENSE_CODES.items() if k in low), str(v))


def _api_frame(f: str, columns: list[str] | None) -> pd.DataFrame | None:
    """One per-species API export, normalised to the column names and codes a GBIF download uses."""
    try:
        d = pd.read_csv(f, dtype=str, keep_default_na=False, on_bad_lines="skip")
    except Exception:
        return None
    if "issues" in d.columns and "issue" not in d.columns:
        d = d.rename(columns={"issues": "issue"})
    if "issue" in d.columns:
        d["issue"] = d["issue"].str.replace(r"[\[\]' ]", "", regex=True).str.replace(",", ";")
    if "license" in d.columns:
        d["license"] = d["license"].map(_license_code)
    want = set(columns) if columns else set(REQUIRED + OPTIONAL)
    keep = [c for c in d.columns if c in want]
    return d[keep] if keep else None


def iter_chunks(path: Path, chunksize: int = 250_000, columns: list[str] | None = None):
    info = detect_format(path)
    fmt = info["format"]
    if fmt == "api_csv_dir":
        SKIPPED_FILES.clear()
        buf, n = [], 0
        for f in info["files"]:
            d = _api_frame(f, columns)
            if d is None or not len(d) or not set(REQUIRED) - {"taxonKey"} <= set(d.columns):
                SKIPPED_FILES.append(Path(f).name)
                continue
            buf.append(d)
            n += len(d)
            if n >= chunksize:
                yield pd.concat(buf, ignore_index=True)
                buf, n = [], 0
        if buf:
            yield pd.concat(buf, ignore_index=True)
        return
    if fmt == "parquet":
        try:
            import pyarrow.dataset as ds
        except ImportError as e:
            raise GbifFormatError("Parquet input needs pyarrow (pip install pyarrow), or re-download as SIMPLE_CSV.") from e
        for batch in ds.dataset(info["file"], format="parquet").to_batches(columns=columns, batch_size=chunksize):
            yield batch.to_pandas()
        return
    kw = dict(sep=info["sep"], chunksize=chunksize, dtype=str, keep_default_na=False, on_bad_lines="skip",
              quoting=3 if info["sep"] == "\t" else 0, usecols=(lambda c: c in set(columns)) if columns else None)
    if fmt in ("dwca_zip", "simple_csv_zip"):
        with zipfile.ZipFile(info["file"]) as z, z.open(info["member"]) as f:
            yield from pd.read_csv(f, **kw)
    else:
        yield from pd.read_csv(info["file"], **kw)


def inspect(path: Path, sample_rows: int = 50_000) -> dict:
    info = detect_format(path)
    first = next(iter_chunks(path, chunksize=sample_rows), None)
    if first is None:
        raise GbifFormatError("The file has no rows.")
    cols = list(first.columns)
    # SIMPLE_CSV uses speciesKey/taxonKey interchangeably in some exports; accept either
    have = set(cols)
    missing = [c for c in REQUIRED if c not in have and not (c == "taxonKey" and "speciesKey" in have)]
    out = {**info, "columns": cols, "sample_rows": len(first), "missing_required": missing,
           "optional_missing": [c for c in OPTIONAL if c not in have]}
    if "year" in have:
        y = pd.to_numeric(first["year"], errors="coerce").dropna()
        out["year_range_sample"] = [int(y.min()), int(y.max())] if len(y) else None
    if "basisOfRecord" in have:
        out["basis_of_record_sample"] = first["basisOfRecord"].value_counts().head(6).to_dict()
    out["advice"] = (f"Re-request the download including these columns: {missing}" if missing else "All required columns present.")
    return out


# ------------------------------------------------------------------ regions
def load_boxes(path: Path = BOXES_PATH) -> pd.DataFrame:
    return pd.read_csv(path).sort_values("priority")


def assign_regions(lat: pd.Series, lon: pd.Series, boxes: pd.DataFrame | None = None) -> pd.Series:
    """Approximate NOAA region from lat/lon boxes (first matching priority wins). Replace with real polygons when available."""
    boxes = load_boxes() if boxes is None else boxes
    out = pd.Series(pd.NA, index=lat.index, dtype="object")
    for b in boxes.itertuples():
        m = out.isna() & lat.between(b.lat_min, b.lat_max) & lon.between(b.lon_min, b.lon_max)
        out[m] = b.region
    return out


# ------------------------------------------------------------------ gate
class SeenHashes:
    """64-bit hashes of rows already accepted, kept as sorted numpy arrays (8 bytes per row) so duplicates are found across chunks."""

    def __init__(self):
        self._parts: list[np.ndarray] = []

    def contains(self, h: np.ndarray) -> np.ndarray:
        if not self._parts:
            return np.zeros(len(h), dtype=bool)
        return np.isin(h, np.concatenate(self._parts))

    def add(self, h: np.ndarray) -> None:
        if len(h):
            self._parts.append(np.unique(h))
            if len(self._parts) > 16:
                self._parts = [np.unique(np.concatenate(self._parts))]


DUP_KEY = ["taxon", "lat", "lon", "year_i", "month_i", "eventDate", "datasetKey"]


def _row_hash(d: pd.DataFrame) -> np.ndarray:
    """Content key for duplicates. eventDate is part of it, so separate visits to the same site in the same month are
    not mistaken for copies of one record."""
    return pd.util.hash_pandas_object(d[DUP_KEY].astype(str), index=False).to_numpy()


def classify(raw: pd.DataFrame, allow_noncommercial: bool = False, seen: SeenHashes | None = None) -> pd.DataFrame:
    """One status per row with reason codes: VALID / REVIEW / REJECTED. Adds lat, lon, year_i, month_i, taxon."""
    d = raw.copy()
    if "taxonKey" not in d.columns and "speciesKey" in d.columns:
        d["taxonKey"] = d["speciesKey"]
    missing = [c for c in REQUIRED if c not in d.columns]
    if missing:
        raise GbifFormatError(f"Missing required columns: {missing}")
    for c in OPTIONAL:
        if c not in d.columns:
            d[c] = ""
    d["lat"] = pd.to_numeric(d["decimalLatitude"], errors="coerce")
    d["lon"] = pd.to_numeric(d["decimalLongitude"], errors="coerce")
    d["year_i"] = pd.to_numeric(d["year"], errors="coerce")
    d["month_i"] = pd.to_numeric(d["month"], errors="coerce")
    d["taxon"] = pd.to_numeric(d["taxonKey"], errors="coerce")
    unc = pd.to_numeric(d["coordinateUncertaintyInMeters"], errors="coerce")
    issue = d["issue"].fillna("").astype(str)
    basis = d["basisOfRecord"].fillna("").astype(str).str.upper()
    reasons = pd.Series("", index=d.index, dtype="object")

    def add(mask, code):
        reasons[mask] = reasons[mask] + code + ";"

    add(d["taxon"].isna(), "missing_taxon_key")
    add(d["lat"].isna() | d["lon"].isna(), "missing_coordinates")
    add((d["lat"] == 0) & (d["lon"] == 0), "zero_coordinates")
    add((d["lat"].abs() > 90) | (d["lon"].abs() > 180), "coordinates_out_of_range")
    add(d["occurrenceStatus"].fillna("").astype(str).str.upper() == "ABSENT", "absence_record")
    add(basis.isin(["FOSSIL_SPECIMEN", "LIVING_SPECIMEN"]), "fossil_or_living_specimen")
    add(d["year_i"].isna() | (d["year_i"] < MIN_YEAR) | (d["year_i"] > MAX_YEAR), "bad_year")
    bad_issue = pd.Series(False, index=d.index)
    for code in BAD_ISSUES:
        bad_issue |= issue.str.contains(code, regex=False)
    add(bad_issue, "gbif_coordinate_issue")
    hard = reasons != ""
    dup = pd.Series(False, index=d.index)
    live = d[~hard]                      # duplicates are judged among rows still standing, so a rejected copy never condemns a good row
    h = _row_hash(live)
    gid = live["gbifID"].astype(str).str.strip()
    in_chunk = np.array(live.duplicated(DUP_KEY, keep="first").to_numpy(), dtype=bool) | \
        np.array((gid.ne("") & gid.duplicated(keep="first")).to_numpy(), dtype=bool)        # the same GBIF record twice
    earlier = seen.contains(h) if seen is not None else np.zeros(len(h), dtype=bool)
    dup[live.index] = in_chunk | earlier
    if seen is not None:
        seen.add(h[~(in_chunk | earlier)])
    add(dup, "exact_duplicate")
    hard = reasons != ""
    # review rules
    ok = ~hard
    add(ok & (unc > MAX_UNCERTAINTY_M), "coordinate_uncertainty_over_10km")
    # GBIF's COORDINATE_ROUNDED issue only means rounding to 5 decimals (about 1 m), so it is not low precision;
    # whole-degree coordinates (about 100 km) are
    rounded = ok & (d["lat"] % 1 == 0) & (d["lon"] % 1 == 0)
    add(rounded, "coordinates_rounded_low_precision")
    add(ok & (basis == "PRESERVED_SPECIMEN") & (d["year_i"] < OLD_SPECIMEN_YEAR), "old_preserved_specimen")
    add(ok & d["establishmentMeans"].fillna("").astype(str).str.upper().isin(["INTRODUCED", "INVASIVE", "VAGRANT", "MANAGED"]),
        "not_native_or_managed")
    if not allow_noncommercial:
        add(ok & d["license"].fillna("").astype(str).str.upper().str.contains("NC", regex=False), "license_non_commercial")
    status = pd.Series("VALID", index=d.index, dtype="object")
    status[reasons != ""] = "REVIEW"
    status[hard] = "REJECTED"
    d["status"], d["reasons"] = status, reasons.str.rstrip(";")
    return d


def report_from_counts(status_counts: dict, reason_counts: dict, rows: int) -> dict:
    valid = status_counts.get("VALID", 0)
    return {"total_rows": rows, "by_status": dict(status_counts), "reason_counts": dict(sorted(reason_counts.items(), key=lambda kv: -kv[1])),
            "valid_rows": valid, "pass_rate": round(valid / max(rows, 1), 4)}


# ------------------------------------------------------------------ aggregation (mergeable)
def _cell(v: pd.Series) -> pd.Series:
    return (np.floor(v / GRID_DEG) * GRID_DEG + GRID_DEG / 2).round(4)


class Aggregator:
    """Collects mergeable sums across chunks; call frames() at the end."""

    def __init__(self, boxes: pd.DataFrame | None = None):
        self.boxes = load_boxes() if boxes is None else boxes
        self.cells, self.month, self.year, self.taxa, self.points = [], [], [], [], []
        self._rows = 0

    def add(self, valid: pd.DataFrame) -> None:
        if valid.empty:
            return
        v = valid.assign(region=assign_regions(valid["lat"], valid["lon"], self.boxes).fillna("Outside NOAA regions"),
                         cell_lat=_cell(valid["lat"]), cell_lon=_cell(valid["lon"]))
        v["month_i"] = v["month_i"].where(v["month_i"].between(1, 12))
        self.cells.append(v.groupby(["taxon", "cell_lat", "cell_lon", "year_i"], as_index=False).size().rename(columns={"size": "n"}))
        m = v.dropna(subset=["month_i"])
        self.month.append(m.groupby(["taxon", "region", "month_i"], as_index=False).size().rename(columns={"size": "n"}))
        self.year.append(v.groupby(["taxon", "region", "year_i"], as_index=False).agg(
            n=("lat", "size"), lat_sum=("lat", "sum"), lon_sum=("lon", "sum"), lat_min=("lat", "min"), lat_max=("lat", "max")))
        self.taxa.append(v.groupby("taxon", as_index=False).agg(
            n_valid=("lat", "size"), species=("species", "first"), genus=("genus", "first"), family=("family", "first"),
            scientific_name=("scientificName", "first")))
        h = pd.util.hash_pandas_object(v[["taxon", "lat", "lon", "year_i"]], index=False).astype("uint64")
        keep = v.assign(_h=h).sort_values(["taxon", "_h"]).groupby("taxon").head(POINTS_PER_TAXON)   # deterministic sample per chunk
        self.points.append(keep[["taxon", "lat", "lon", "year_i", "region"]])
        if len(self.cells) >= 20:
            self._compact()

    def _compact(self) -> None:
        def red(frames, keys, agg):
            if not frames:
                return frames
            df = pd.concat(frames, ignore_index=True)
            return [df.groupby(keys, as_index=False).agg(agg)]
        self.cells = red(self.cells, ["taxon", "cell_lat", "cell_lon", "year_i"], {"n": "sum"})
        self.month = red(self.month, ["taxon", "region", "month_i"], {"n": "sum"})
        self.year = red(self.year, ["taxon", "region", "year_i"], {"n": "sum", "lat_sum": "sum", "lon_sum": "sum", "lat_min": "min", "lat_max": "max"})
        self.taxa = red(self.taxa, ["taxon"], {"n_valid": "sum", "species": "first", "genus": "first", "family": "first", "scientific_name": "first"})
        if self.points:
            p = pd.concat(self.points, ignore_index=True)
            h = pd.util.hash_pandas_object(p[["taxon", "lat", "lon", "year_i"]], index=False).astype("uint64")
            self.points = [p.assign(_h=h).sort_values(["taxon", "_h"]).groupby("taxon").head(POINTS_PER_TAXON).drop(columns="_h")]

    def frames(self) -> dict:
        self._compact()
        e = lambda x, cols: x[0] if x else pd.DataFrame(columns=cols)    # noqa: E731
        out = {"cells": e(self.cells, ["taxon", "cell_lat", "cell_lon", "year_i", "n"]),
               "month": e(self.month, ["taxon", "region", "month_i", "n"]),
               "year": e(self.year, ["taxon", "region", "year_i", "n", "lat_sum", "lon_sum", "lat_min", "lat_max"]),
               "taxa": e(self.taxa, ["taxon", "n_valid", "species", "genus", "family", "scientific_name"]),
               "points": e(self.points, ["taxon", "lat", "lon", "year_i", "region"])}
        out["taxa"]["taxon"] = out["taxa"]["taxon"].astype("int64")
        return out


# ------------------------------------------------------------------ build
def sha256(path: Path, limit_mb: int = 64) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(limit_mb * 1_000_000))
    return h.hexdigest()[:16]


def build(source: Path, lake: Path | None = None, chunksize: int = 250_000, allow_noncommercial: bool = False,
          doi: str = "", is_test_fixture: bool = False, built_at: str | None = None, progress=None) -> dict:
    """Stream the download through the gate and write gold tables + manifest + validation report into the lake."""
    lake = Path(lake or LAKE)
    gold, reports = lake / "gold", lake / "reports"
    gold.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    agg, status_counts, reason_counts, rows, seen = Aggregator(), {}, {}, 0, SeenHashes()
    for i, chunk in enumerate(iter_chunks(source, chunksize)):
        c = classify(chunk, allow_noncommercial, seen)
        rows += len(c)
        for k, v in c["status"].value_counts().items():
            status_counts[k] = status_counts.get(k, 0) + int(v)
        for k, v in c["reasons"][c["reasons"] != ""].str.split(";").explode().value_counts().items():
            reason_counts[k] = reason_counts.get(k, 0) + int(v)
        agg.add(c[c["status"] == "VALID"])
        if progress:
            progress(i, rows)
    fr = agg.frames()
    names = {"cells": "gbif_cells_year", "month": "gbif_month", "year": "gbif_year_stats", "taxa": "gbif_taxa", "points": "gbif_points_sample"}
    for k, name in names.items():
        fr[k].to_csv(gold / f"{name}.csv.gz", index=False)
    rep = report_from_counts(status_counts, reason_counts, rows)
    (reports / "gbif_validation_report.json").write_text(json.dumps(rep, indent=2))
    kind = detect_format(source)["format"]
    manifest = {"source": str(source), "source_kind": "api_sample" if kind == "api_csv_dir" else "download",
                "skipped_files": list(SKIPPED_FILES)[:50] if kind == "api_csv_dir" else [],
                "source_sha256_first64mb": sha256(Path(source)) if Path(source).is_file() else None,
                "doi": doi, "is_test_fixture": is_test_fixture, "allow_noncommercial": allow_noncommercial, "grid_deg": GRID_DEG,
                "region_method": "approximate lat/lon boxes (replace with polygons)", "rows": rows, "valid_rows": rep["valid_rows"],
                "taxa": int(len(fr["taxa"])), "built_at": built_at or time.strftime("%Y-%m-%dT%H:%M:%S")}
    (lake / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"manifest": manifest, "report": rep}


# ------------------------------------------------------------------ read side
class Gold:
    """Small read-only view over the gold tables. Loads lazily."""

    def __init__(self, lake: Path | None = None):
        self.lake = Path(lake or LAKE)
        self._t: dict = {}

    @property
    def available(self) -> bool:
        return (self.lake / "manifest.json").exists()

    @property
    def manifest(self) -> dict:
        return json.loads((self.lake / "manifest.json").read_text()) if self.available else {}

    @property
    def report(self) -> dict:
        p = self.lake / "reports" / "gbif_validation_report.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def table(self, name: str) -> pd.DataFrame:
        if name not in self._t:
            self._t[name] = pd.read_csv(self.lake / "gold" / f"gbif_{name}.csv.gz")
        return self._t[name]

    cells = property(lambda self: self.table("cells_year"))
    month = property(lambda self: self.table("month"))
    year = property(lambda self: self.table("year_stats"))
    taxa = property(lambda self: self.table("taxa"))
    points = property(lambda self: self.table("points_sample"))
