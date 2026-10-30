import pandas as pd

from fishmarket import gate as G, loader
from fishmarket.config import DEFAULT
from fishmarket.registry import load_registry

AS_OF = pd.Timestamp("2026-10-15")


def gate_series(species, region, overrides=None, cfg=DEFAULT, only=None):
    """Run the gate for one series using every non-sample source that has rows for it."""
    reg = load_registry(cfg, (overrides or {}).get("registry_path"))
    raws = loader.load_all(cfg, reg, overrides)
    from fishmarket.registry import load_catalog
    cat = load_catalog(cfg)
    ids = [s for s in raws if reg.loc[s, "trust_tier"] != "D" and loader.covers_series(raws[s], species, region)]
    if only:
        ids = [s for s in ids if s in only]
    return G.run_gate(cfg, reg, raws, ids, species, region, AS_OF, cat), reg
