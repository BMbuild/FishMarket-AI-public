"""User-attached evidence (receipts, price sheets, notes). Treated as UNTRUSTED, unverified data.

Rules: files are type- and size-checked, hashed, scanned for AI-instruction text, and never change a NOAA number
or any verdict. A CSV with a price column is parsed and shown NEXT TO the NOAA figure with a plain comparison;
text is shown as a sanitised excerpt. Images/PDFs are stored by hash and listed, but not read."""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import pandas as pd

from . import note

MAX_FILES, MAX_BYTES = 3, 2_000_000
ALLOWED = {".csv": "csv", ".txt": "text", ".md": "text", ".pdf": "stored", ".png": "stored", ".jpg": "stored", ".jpeg": "stored"}
TIER = "user-supplied, unverified"
PRICE_COLS = ("price", "price_per_lb", "usd_per_lb", "price_usd")
UNIT_HINTS = {"lb": 1.0, "kg": 2.2046}   # USD/kg -> USD/lb divide by 2.2046
DISAGREE_PCT = 25.0


def _safe_name(n: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(n).name)[:80] or "file"


def ingest(name: str, data: bytes) -> dict:
    ev = {"name": _safe_name(name), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()[:16], "tier": TIER,
          "flags": [], "problems": []}
    kind = ALLOWED.get(Path(name).suffix.lower())
    if not kind:
        return {**ev, "kind": "rejected", "problems": [f"File type {Path(name).suffix or '(none)'} is not accepted."]}
    if len(data) > MAX_BYTES:
        return {**ev, "kind": "rejected", "problems": [f"File is over {MAX_BYTES // 1_000_000} MB."]}
    ev["kind"] = kind
    if kind == "stored":
        ev["note"] = "Kept by hash only. Its contents are not read or used."
        return ev
    text = data.decode("utf-8", errors="replace")
    sc = note.scan(text, [], "", [], [])
    ev["flags"] = sc["flags"]
    ev["injection_phrases"] = sc["injection_phrases"]
    ev["excerpt"] = note.sanitise(text, 400)["text"]
    if kind == "csv":
        try:
            df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
        except Exception as e:  # malformed file
            ev["problems"].append(f"Could not read as CSV: {type(e).__name__}")
            return ev
        ev["rows"], ev["columns"] = int(len(df)), list(df.columns)[:12]
        ev.update(_price_facts(df))
    return ev


def _price_facts(df: pd.DataFrame) -> dict:
    cols = {c.lower().strip(): c for c in df.columns}
    pc = next((cols[c] for c in PRICE_COLS if c in cols), None)
    if not pc:
        return {"problems": ["No price column found (expected one of: " + ", ".join(PRICE_COLS) + ")."]}
    price = pd.to_numeric(df[pc].str.replace(r"[$,]", "", regex=True), errors="coerce")
    ok = price[price > 0]
    out = {"price_rows_usable": int(len(ok)), "price_rows_unreadable": int(len(price) - len(ok))}
    unit_col = cols.get("unit")
    unit = (df[unit_col].str.lower().str.strip().mode().iat[0] if unit_col and len(df) else "lb")
    if unit not in UNIT_HINTS:
        out["problems"] = [f"Unit '{unit}' not recognised; use lb or kg."]
        return out
    ok = ok / UNIT_HINTS[unit]
    if ok.empty:
        out["problems"] = ["No usable positive prices."]
        return out
    out.update(unit_in_file=unit, median_price_usd_lb=round(float(ok.median()), 3), min_usd_lb=round(float(ok.min()), 3),
               max_usd_lb=round(float(ok.max()), 3))
    return out


def compare_to_noaa(ev: dict, noaa_latest_price: float, year: int) -> dict | None:
    """Plain comparison only. A large gap is shown as a flag, never used to alter the NOAA analysis."""
    m = ev.get("median_price_usd_lb")
    if m is None:
        return None
    gap = (m / noaa_latest_price - 1) * 100
    return {"evidence_median_usd_lb": m, "noaa_year": year, "noaa_price_usd_lb": round(noaa_latest_price, 3),
            "gap_pct": round(gap, 1), "differs_a_lot": abs(gap) >= DISAGREE_PCT,
            "reading": ("Your figure is close to NOAA's annual dockside price." if abs(gap) < DISAGREE_PCT else
                        "Your figure differs a lot from NOAA's annual dockside price. Possible reasons: different market level "
                        "(retail vs dockside), different year, or a unit mix-up. Check before relying on it.")}


def ingest_many(files: list[tuple[str, bytes]]) -> list[dict]:
    out = [ingest(n, d) for n, d in files[:MAX_FILES]]
    if len(files) > MAX_FILES:
        out.append({"name": "(extra files)", "kind": "rejected", "problems": [f"Only {MAX_FILES} files are used; the rest were ignored."],
                    "flags": [], "tier": TIER})
    return out
