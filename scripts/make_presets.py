"""One-off: copy the six preset profiles from the tests-only golden cases into app/presets.json,
so the app itself never reads tests_only/. Run once: python scripts/make_presets.py"""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
golden = json.loads((root / "fishmarket_data" / "tests_only" / "golden_cases.json").read_text())
NEW = ["G13", "G14", "G15", "G16", "G18", "G20", "G21", "G26", "G31", "G36", "G41", "G46"]
presets = [{"id": g["case_id"], "name": g["name"], "profile": g["profile"], "planted_cases": g["planted_cases"]}
           for g in golden if g["kind"] == "preset" or g["case_id"] in NEW]
(root / "app" / "presets.json").write_text(json.dumps(presets, indent=1))
print(f"wrote {len(presets)} presets")
