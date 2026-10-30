"""Everything the QA tools need, loaded once."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .. import crosswalk, gbif, live as live_mod, real_data


@dataclass
class Context:
    noaa: real_data.Loaded
    gold: gbif.Gold
    cw: pd.DataFrame | None
    real_only: bool = False
    allow_synthetic: bool = True
    species: list[str] = field(default_factory=list)       # species with enough history, biggest first
    all_species: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    value_rank: dict = field(default_factory=dict)
    live: bool = False                                     # free live API calls (OBIS, Census trade) allowed
    live_fetch: object = None                              # test hook: replaces the HTTP call

    @classmethod
    def load(cls, lake: Path | None = None, csv: Path | None = None, real_only: bool = False, live: bool | None = None, live_fetch=None) -> "Context":
        noaa = real_data.load(csv)
        gold = gbif.Gold(lake)
        cw = None
        if gold.available:
            cp = gold.lake / "crosswalk" / "species_crosswalk.csv"
            cw = pd.read_csv(cp, keep_default_na=False) if cp.exists() else crosswalk.build(noaa.df, gold.taxa)
        last = int(noaa.df["year"].max())
        val = noaa.df[noaa.df["year"] > last - 5].groupby("species")["dollars"].sum().sort_values(ascending=False)
        return cls(noaa=noaa, gold=gold, cw=cw, real_only=real_only, species=real_data.species_list(noaa.df),
                   all_species=sorted(noaa.df["species"].unique()), regions=sorted(noaa.df["region"].unique()),
                   states=sorted(noaa.states["state"].unique()), value_rank=val.to_dict(),
                   live=(live_mod.enabled() if live is None else live), live_fetch=live_fetch)

    def species_regions(self, species: str) -> list[str]:
        return real_data.regions_for(self.noaa.df, species)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
