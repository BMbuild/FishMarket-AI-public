"""Rung 4 of the fallback ladder: deterministic synthetic companions anchored to real NOAA annual levels.
Everything returned is SYNTHETIC. The real value is only a scale; no real and synthetic number is ever combined."""
from __future__ import annotations

import hashlib
import math

import numpy as np

from .origin import SYNTHETIC, anchor

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def monthly_profile(species: str, region: str, annual_price: float, annual_pounds: float, dataset_id: str = "NOAA-LANDINGS") -> dict:
    """12 monthly prices whose mean equals the real annual price, with a seeded seasonal shape and noise."""
    a = anchor(annual_price, dataset_id)
    rng = np.random.default_rng(_seed(species, region, "monthly-v1"))
    phase = rng.uniform(0, 2 * math.pi)
    amp = rng.uniform(0.06, 0.18)
    shape = 1 + amp * np.sin(2 * math.pi * np.arange(12) / 12 + phase) + rng.normal(0, 0.02, 12)
    shape = shape / shape.mean()
    prices = a.value * shape
    # landings are higher when price is lower (generated, illustrative)
    vol = annual_pounds / 12 * (2 - shape) / (2 - shape).mean()
    return {"origin": SYNTHETIC, "anchored_to": a.anchored_to, "prices": [round(float(p), 3) for p in prices],
            "pounds": [round(float(v), 0) for v in vol], "seed": _seed(species, region, "monthly-v1")}


def best_months(profile: dict, n: int = 3) -> list[tuple[str, float]]:
    order = sorted(range(12), key=lambda i: -profile["prices"][i])[:n]
    return [(MONTHS[i], profile["prices"][i]) for i in order]


def cost_profile(species: str, annual_price: float, dataset_id: str = "NOAA-LANDINGS") -> dict:
    """Fictional per-pound cost structure for a small boat. Every number is SYNTHETIC, including the price it is compared with
    (a seeded stand-in scaled to the real annual price), so no real and synthetic value is ever combined."""
    a = anchor(annual_price, dataset_id)
    rng = np.random.default_rng(_seed(species, "cost-v1"))
    price = a.value * rng.uniform(0.92, 1.08)
    share = {"fuel": rng.uniform(0.08, 0.16), "bait": rng.uniform(0.02, 0.09), "ice": rng.uniform(0.01, 0.03), "labor": rng.uniform(0.25, 0.38),
             "boat and gear upkeep": rng.uniform(0.05, 0.10)}
    costs = {k: round(float(price * v), 3) for k, v in share.items()}
    fresh_hold = round(float(price * rng.uniform(0.004, 0.010)), 3)            # per lb per day on ice
    frozen_month = round(float(price * rng.uniform(0.010, 0.025)), 3)          # per lb per month in a freezer
    total = round(sum(costs.values()), 3)
    return {"origin": SYNTHETIC, "anchored_to": a.anchored_to, "price": round(float(price), 3), "costs": costs, "total": total,
            "margin": round(float(price) - total, 3), "fresh_hold_per_day": fresh_hold, "frozen_per_month": frozen_month,
            "grade_shares": {"A": round(float(rng.uniform(0.55, 0.70)), 2), "B": round(float(rng.uniform(0.20, 0.30)), 2)}, "seed": _seed(species, "cost-v1")}


def trade_profile(group: str, flow: str, landed_value: float, dataset_id: str = "NOAA-LANDINGS") -> dict:
    """Illustrative annual trade value for a product group, a seeded multiple of the real annual landed value. SYNTHETIC."""
    a = anchor(landed_value, dataset_id)
    rng = np.random.default_rng(_seed(group, flow, "trade-v1"))
    mult = rng.uniform(0.4, 3.0) if flow == "imports" else rng.uniform(0.2, 1.5)
    partners = ["Country A", "Country B", "Country C"]
    w = rng.dirichlet([3, 2, 1])
    total = a.value * mult
    return {"origin": SYNTHETIC, "anchored_to": a.anchored_to, "total_usd": float(total), "partners": [(p, float(total * x)) for p, x in zip(partners, w)], "seed": _seed(group, flow, "trade-v1")}
