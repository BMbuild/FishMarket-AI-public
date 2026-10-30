"""Reads source files from the local data folder. Rule 3: only `overrides` can point at planted files."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, TypedDict

import pandas as pd

from .config import Config, DEFAULT

REQUIRED_COLUMNS = ["date", "region", "species", "source_type", "price", "volume", "unit",
                    "channel", "source_id", "retrieved_on"]



class Overrides(TypedDict, total=False):
    registry_path: Optional[str]
    source_files: dict       # source_id -> file (price series)
    dataset_files: dict      # dataset name (market_prices, markets, quality_records, input_costs) -> file

DATASET_FILES = {"market_prices": "data/market_prices.csv", "markets": "registry/markets.csv",
                 "quality_records": "data/quality_records.csv", "input_costs": "data/input_costs.csv"}


def source_path(cfg: Config, registry_row, overrides: Optional[Overrides]) -> Path:
    sid = registry_row["source_id"]
    if overrides and overrides.get("source_files", {}).get(sid):
        p = Path(overrides["source_files"][sid])
    else:
        p = Path(registry_row["file"])
    return p if p.is_absolute() else cfg.DATA_DIR / p


def load_raw(path: Path) -> pd.DataFrame:
    """Read every cell as text so the gate, not pandas, decides what is parseable."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def load_all(cfg: Config, registry: pd.DataFrame, overrides: Optional[Overrides]) -> dict[str, pd.DataFrame]:
    out = {}
    for sid, row in registry.iterrows():
        if row.get("dataset_kind", "price_series") != "price_series":
            continue
        p = source_path(cfg, row, overrides)
        out[sid] = load_raw(p) if p.exists() else pd.DataFrame(columns=REQUIRED_COLUMNS)
    return out


def covers_series(raw: pd.DataFrame, species: str, region: str) -> bool:
    if raw.empty or not {"species", "region"} <= set(raw.columns):
        return False
    return bool(((raw["species"] == species) & (raw["region"] == region)).any())


def load_dataset(cfg: Config, name: str, overrides: Optional[Overrides] = None) -> pd.DataFrame:
    """Auxiliary datasets (market postings, markets, quality records, input costs). Only `overrides` can
    point at planted files (rule 3)."""
    rel = (overrides or {}).get("dataset_files", {}).get(name) or DATASET_FILES[name]
    p = Path(rel)
    p = p if p.is_absolute() else cfg.DATA_DIR / p
    return pd.read_csv(p, keep_default_na=False)


def load_reference(cfg: Config, name: str) -> pd.DataFrame:
    return pd.read_csv(cfg.DATA_DIR / "reference" / f"{name}.csv", keep_default_na=False)


def overrides_from_manifest(cfg: Config, case_ids: list[str]) -> Overrides:
    """Build overrides from planted_manifest.json. Used by tests and the UI toggles only.
    Cases that replace several files (override_files) are applied together."""
    import json
    manifest = json.loads((cfg.DATA_DIR / "planted" / "planted_manifest.json").read_text())
    by_id = {m["case_id"]: m for m in manifest}
    reg_ids = set(pd.read_csv(cfg.DATA_DIR / "registry" / "source_registry.csv")["source_id"])
    ov: Overrides = {"registry_path": None, "source_files": {}, "dataset_files": {}}
    seen: dict[str, str] = {}
    for cid in case_ids:
        m = by_id[cid]
        targets = dict(m.get("override_files") or {m["replaces_source_id"]: m["file"]})
        for name, f in targets.items():
            if name in seen:
                raise ValueError(f"{cid} and {seen[name]} both replace {name}; choose one.")
            seen[name] = cid
            (ov["source_files"] if name in reg_ids else ov["dataset_files"])[name] = f
        if m["registry_file"] != "registry/source_registry.csv":
            ov["registry_path"] = m["registry_file"]
    return ov


def planted_cases(cfg: Config) -> list[dict]:
    """Case id, what it replaces and a one-line description, for the UI's planted-problem toggles."""
    import json
    manifest = json.loads((cfg.DATA_DIR / "planted" / "planted_manifest.json").read_text())
    return [{"case_id": m["case_id"], "replaces": "+".join(m["override_files"]) if m.get("override_files")
             else m["replaces_source_id"], "injected": m["injected"]} for m in manifest]
