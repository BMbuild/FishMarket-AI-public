"""Source registry and species catalog loaders."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import Config, DEFAULT

TIER_RANK = {"A": 3, "B": 2, "C": 1, "D": 0}
REGISTRY_COLUMNS = ["source_id", "name", "owner", "source_kind", "trust_tier", "update_cadence_days",
                    "last_updated", "file", "has_volume", "price_basis", "expected_markup_vs_first_sale",
                    "covers", "notes"]


def load_registry(cfg: Config = DEFAULT, path: str | Path | None = None) -> pd.DataFrame:
    """Registry indexed by source_id. `path` is relative to the data folder unless absolute."""
    p = Path(path) if path else cfg.DATA_DIR / "registry" / "source_registry.csv"
    if not p.is_absolute():
        p = cfg.DATA_DIR / p
    df = pd.read_csv(p)
    missing = [c for c in REGISTRY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Registry {p.name} is missing columns: {missing}")
    if "dataset_kind" not in df.columns:
        df["dataset_kind"] = "price_series"
    df["has_volume"] = df["has_volume"].astype(str).str.lower().eq("true")
    df["last_updated"] = pd.to_datetime(df["last_updated"])
    return df.set_index("source_id", drop=False)


def load_catalog(cfg: Config = DEFAULT) -> pd.DataFrame:
    df = pd.read_csv(cfg.DATA_DIR / "registry" / "species_catalog.csv")
    df["region_list"] = df["regions"].str.split(";")
    return df.set_index("species", drop=False)


def species_for_region(catalog: pd.DataFrame, region: str) -> list[str]:
    return [s for s, r in catalog["region_list"].items() if region in r]


def tier(registry: pd.DataFrame, source_id: str) -> str:
    return str(registry.loc[source_id, "trust_tier"])


def rank(registry: pd.DataFrame, source_id: str) -> int:
    return TIER_RANK[tier(registry, source_id)]


def price_sources(registry: pd.DataFrame) -> list[str]:
    """Registry rows that hold price series (the gate works on these)."""
    return [s for s in registry.index if registry.loc[s, "dataset_kind"] == "price_series"]


def load_operations(cfg: Config = DEFAULT) -> pd.DataFrame:
    df = pd.read_csv(cfg.DATA_DIR / "registry" / "operation_types.csv", keep_default_na=False)
    df["allowed"] = df["allowed_question_types"].str.split(";")
    df["costs"] = df["cost_types"].str.split(";")
    return df.set_index("operation_id", drop=False)


def load_segments(cfg: Config = DEFAULT) -> pd.DataFrame:
    return pd.read_csv(cfg.DATA_DIR / "registry" / "customer_segments.csv").set_index("segment_id", drop=False)


def regions(catalog: pd.DataFrame) -> list[str]:
    out: list[str] = []
    for lst in catalog["region_list"]:
        for r in lst:
            if r not in out:
                out.append(r)
    return out
