from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PATH = Path(__file__).with_name("catalogue.yaml")


@lru_cache(maxsize=1)
def load() -> dict:
    entries = yaml.safe_load(PATH.read_text())
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate catalogue ids"
    for e in entries:
        assert len(e["examples"]) >= 5, f"{e['id']} needs at least 5 example phrasings"
        assert e["kind"] in ("real_only", "real_plus_fill", "needs_fill_data")
    return {e["id"]: e for e in entries}


def ids() -> list[str]:
    return list(load())
