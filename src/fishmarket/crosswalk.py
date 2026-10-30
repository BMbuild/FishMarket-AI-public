"""Links NOAA species to GBIF taxa. Never guesses: anything uncertain is `genus_level`, `group` or `none`, and listed for review.

match_type:
  override     curated synonym from data_real/crosswalk/species_overrides.csv (human-verified list; verify against the GBIF backbone)
  exact        NOAA scientific binomial equals a GBIF species name that exists in the loaded GBIF data
  genus_level  NOAA gives only a genus; matched to every GBIF species of that genus present in the data (answers say 'genus-level')
  group        NOAA name is a family, order, 'spp.' group or a mixed category; no species-level link
  none         no scientific name, or not present in the GBIF data
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES = ROOT / "data_real" / "crosswalk" / "species_overrides.csv"
FAMILY_SUFFIXES = ("idae", "inae", "ales", "formes")


def norm(name) -> str:
    return re.sub(r"\s+", " ", str(name).replace("*", " ").strip().lower()) if isinstance(name, str) else ""


def binomial(name: str) -> str:
    parts = re.sub(r"[^A-Za-z\s-]", " ", str(name)).split()
    return " ".join(parts[:2]).lower() if len(parts) >= 2 else ""


def _kind(sci: str) -> str:
    s = norm(sci)
    if not s:
        return "none"
    toks = s.split()
    if "spp" in s or "spp." in s or "sp." in toks:
        return "group"
    if len(toks) == 1:
        return "group" if toks[0].endswith(FAMILY_SUFFIXES) else "genus"
    return "binomial"


def build(noaa_df: pd.DataFrame, taxa: pd.DataFrame, overrides_path: Path = OVERRIDES) -> pd.DataFrame:
    """noaa_df: real_data.Loaded.df (needs species, scientific). taxa: Gold.taxa (taxon, species, genus, n_valid)."""
    t = taxa.assign(sp=taxa["species"].map(norm), ge=taxa["genus"].map(norm))
    by_species = t.groupby("sp")["taxon"].apply(list).to_dict()
    by_genus = t.groupby("ge")["taxon"].apply(list).to_dict()
    ov = pd.read_csv(overrides_path) if Path(overrides_path).exists() else pd.DataFrame(columns=["noaa_scientific", "gbif_species"])
    ov_map = {norm(a): norm(b) for a, b in zip(ov["noaa_scientific"], ov["gbif_species"])}
    names = (noaa_df.dropna(subset=["scientific"]).groupby("species", as_index=False)
             .agg(scientific=("scientific", "first"), ts_afs_name=("ts_afs_name", "first")))
    missing = sorted(set(noaa_df["species"]) - set(names["species"]))
    rows = []
    for r in names.itertuples():
        sci = r.scientific
        kind = _kind(sci)
        keys, mtype, conf, by = [], "none", 0.0, ""
        b = binomial(sci)
        if b and b in ov_map and ov_map[b] in by_species:
            keys, mtype, conf, by = by_species[ov_map[b]], "override", 0.95, "curated override"
        elif kind == "binomial" and b in by_species:
            keys, mtype, conf, by = by_species[b], "exact", 1.0, "scientific name"
        elif kind == "genus" and norm(sci) in by_genus:
            keys, mtype, conf, by = by_genus[norm(sci)], "genus_level", 0.5, "genus"
        elif kind in ("group", "genus"):
            mtype = "group" if kind == "group" else "none"
        rows.append({"noaa_species": r.species, "ts_afs_name": r.ts_afs_name, "noaa_scientific": sci.strip(), "kind": kind,
                     "gbif_taxon_keys": ";".join(str(int(k)) for k in keys), "match_type": mtype, "confidence": conf, "matched_by": by})
    rows += [{"noaa_species": s, "ts_afs_name": "", "noaa_scientific": "", "kind": "none", "gbif_taxon_keys": "",
              "match_type": "none", "confidence": 0.0, "matched_by": "no scientific name in NOAA file"} for s in missing]
    return pd.DataFrame(rows)


def taxon_keys(cw: pd.DataFrame, noaa_species: str) -> tuple[list[int], str]:
    r = cw[cw["noaa_species"] == noaa_species]
    if r.empty or not r.iloc[0]["gbif_taxon_keys"]:
        return [], (r.iloc[0]["match_type"] if len(r) else "none")
    return [int(k) for k in str(r.iloc[0]["gbif_taxon_keys"]).split(";")], r.iloc[0]["match_type"]


def review_table(cw: pd.DataFrame) -> pd.DataFrame:
    """Everything a human should look at: all non-exact matches."""
    return cw[cw["match_type"] != "exact"].sort_values(["match_type", "noaa_species"]).reset_index(drop=True)
