"""Refresh a replay snapshot and its cache entries after an intentional prompt change.

    python scripts/approve.py G01 [--mix dev|final] [--mode auto|live]

Runs the preset (live calls cost money; auto mode reuses the cache), then:
  * copies the cache entries that run used into cache/approved/   (the committed demo backup)
  * writes tests/snapshots/<preset>.json                          (what replay mode must reproduce)
Review the snapshot diff before committing."""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fishmarket import pipeline  # noqa: E402
from fishmarket.config import DEFAULT  # noqa: E402
from fishmarket.llm import LLM, RunCtx  # noqa: E402
from fishmarket.loader import overrides_from_manifest  # noqa: E402
from fishmarket.report import normalize_result  # noqa: E402


def approve(preset_id: str, cfg=DEFAULT, llm=None, mix: str = "dev", snapshot_dir: Path | None = None) -> dict:
    presets = {p["id"]: p for p in json.loads(cfg.PRESETS_PATH.read_text())}
    preset = presets[preset_id]
    ov = overrides_from_manifest(cfg, preset["planted_cases"]) if preset["planted_cases"] else None
    llm = llm or LLM(cfg, mode="auto")
    captured = {}
    orig = pipeline.RunCtx

    class Spy(RunCtx):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            captured["ctx"] = self
    pipeline.RunCtx = Spy
    try:
        res = pipeline.run(preset["profile"], ov, llm=llm, cfg=cfg, mix=mix, save=False)
    finally:
        pipeline.RunCtx = orig
    approved = cfg.CACHE_DIR / "approved"
    approved.mkdir(parents=True, exist_ok=True)
    for key in captured["ctx"].cache_keys:
        for folder in (cfg.CACHE_DIR, approved):
            f = folder / f"{key}.json"
            if f.exists():
                if folder != approved:
                    shutil.copy(f, approved / f.name)
                break
    out = snapshot_dir or (ROOT / "tests" / "snapshots")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{preset_id}.json").write_text(json.dumps(normalize_result(res), indent=1, sort_keys=True))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("preset")
    ap.add_argument("--mix", default="dev", choices=["dev", "final"])
    ap.add_argument("--mode", default="auto", choices=["auto", "live"])
    a = ap.parse_args()
    res = approve(a.preset, DEFAULT, LLM(DEFAULT, mode=a.mode), a.mix)
    print(f"approved {a.preset}: cost ${res['report']['cost']['total_usd']:.4f}; snapshot written")
