"""Level 2: free replay regression. Snapshots come from `scripts/approve.py` after a real run;
until the team has approved a preset, its test is skipped (never faked)."""
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from fishmarket.config import DEFAULT, ROOT
from fishmarket.fake_agents import StubAnthropicClient, fake_llm
from fishmarket.llm import LLM
from fishmarket.loader import overrides_from_manifest
from fishmarket.pipeline import run
from fishmarket.report import normalize_result

sys.path.insert(0, str(ROOT / "scripts"))
from approve import approve  # noqa: E402

PRESETS = json.loads(DEFAULT.PRESETS_PATH.read_text())


@pytest.mark.parametrize("preset", [p["id"] for p in PRESETS])
def test_replay_matches_snapshot(preset, cfg):
    snap = ROOT / "tests" / "snapshots" / f"{preset}.json"
    if not snap.exists():
        pytest.skip(f"no approved snapshot for {preset} yet (run scripts/approve.py {preset} after a live run)")
    p = next(x for x in PRESETS if x["id"] == preset)
    ov = overrides_from_manifest(DEFAULT, p["planted_cases"]) if p["planted_cases"] else None
    c = replace(cfg, CACHE_DIR=DEFAULT.CACHE_DIR, LLM_MODE="replay")      # read the committed approved cache
    res = run(p["profile"], ov, llm=LLM(c, mode="replay"), cfg=c, save=False)
    assert normalize_result(res) == json.loads(snap.read_text())
    assert res["report"]["cost"]["total_usd"] == 0.0


def test_approve_script_roundtrip(cfg, tmp_path):
    """The machinery works end to end with a stubbed SDK: approve, then replay reproduces the snapshot."""
    stub = StubAnthropicClient(fake_llm(cfg))
    snaps = tmp_path / "snaps"
    approve("G06", cfg, LLM(cfg, "auto", client=stub), snapshot_dir=snaps)
    assert len(list((cfg.CACHE_DIR / "approved").glob("*.json"))) == 3
    for f in cfg.CACHE_DIR.glob("*.json"):
        f.unlink()                                     # only the approved copies remain
    p = next(x for x in PRESETS if x["id"] == "G06")
    ov = overrides_from_manifest(DEFAULT, p["planted_cases"])
    res = run(p["profile"], ov, llm=LLM(cfg, mode="replay"), cfg=cfg, save=False)
    assert normalize_result(res) == json.loads((snaps / "G06.json").read_text())
