"""The four read-only tools named in the PRD. Plain Python functions, no AI, no writes.
Each returns dated, unit-labelled rows so nothing is shown without its source and unit."""
from __future__ import annotations

import pandas as pd

from . import real_data
from .config import DEFAULT, Config
from .loader import load_dataset


def get_fish_prices(species: str, region: str | None = None, real: pd.DataFrame | None = None,
                    cfg: Config = DEFAULT) -> list[dict]:
    """Real annual dockside prices when `real` (from real_data.load().df) is given, else fictional monthly market prices."""
    if real is not None:
        s = real_data.series(real, species, region)
        return [{"date": f"{int(r.year)}", "species": species, "region": region or "All regions", "price": round(float(r.price), 3),
                 "unit": "USD/lb", "basis": "annual ex-vessel", "source": real_data.SOURCE_LABEL} for r in s.itertuples()]
    df = load_dataset(cfg, "market_prices")
    df = df[df["species"] == species]
    if region:
        df = df[df["region"] == region]
    return [{"date": r.date, "species": r.species, "region": r.region, "price": float(r.price), "unit": r.unit,
             "basis": r.channel, "source": r.source_id + " (fictional)"} for r in df.itertuples()]


def get_fish_quality(species: str, region: str | None = None, cfg: Config = DEFAULT) -> list[dict]:
    """Fictional quality records only; NOAA landings carry no quality data."""
    df = load_dataset(cfg, "quality_records")
    df = df[df["species"] == species]
    if region:
        df = df[df["region"] == region]
    return [{"date": r.date, "grade": r.grade, "freshness_days": r.freshness_days, "status": r.verification_status,
             "source": r.source_id + " (fictional)"} for r in df.itertuples()]


def compare_market_price(species: str, region_a: str, region_b: str, real: pd.DataFrame) -> dict:
    """Latest-year dockside price in two regions, from real data. Positive gap means region_a pays more."""
    a, b = (real_data.series(real, species, r) for r in (region_a, region_b))
    if a.empty or b.empty:
        return {"ok": False, "reason": "One of the regions has no data for this species."}
    year = int(min(a["year"].max(), b["year"].max()))
    pa, pb = float(a[a.year == year].price.iloc[0]), float(b[b.year == year].price.iloc[0])
    return {"ok": True, "year": year, "unit": "USD/lb", region_a: round(pa, 3), region_b: round(pb, 3),
            "gap_pct": round((pa / pb - 1) * 100, 1), "source": real_data.SOURCE_LABEL}


def validate_market_data(rows: list[dict]) -> dict:
    """Cheap sanity check any tool output must pass before use: dated, unit-labelled, positive price."""
    problems = []
    for i, r in enumerate(rows):
        for k in ("date", "unit", "source"):
            if not r.get(k):
                problems.append(f"row {i}: missing {k}")
        p = r.get("price")
        if p is None or not isinstance(p, (int, float)) or p <= 0:
            problems.append(f"row {i}: price must be a positive number")
    return {"ok": not problems, "problems": problems[:20], "rows": len(rows)}
