"""python -m fishmarket.cli run --preset G01 [--mix dev|final] [--mode auto|live|replay|fake] [--planted PP-STALE ...]"""
from __future__ import annotations

import argparse
import json
import sys

from .config import DEFAULT
from .llm import LLM, LLMError
from .loader import overrides_from_manifest
from .pipeline import ProfileError, run

ICON = {"done": "ok ", "warning": "!! ", "retrying": "<> ", "failed": "XX ", "fallback": "-> ", "running": "...",
        "pending": "   "}


def load_presets(cfg=DEFAULT) -> dict:
    return {p["id"]: p for p in json.loads(cfg.PRESETS_PATH.read_text())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fishmarket")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run one analysis")
    r.add_argument("--preset", default="G01")
    r.add_argument("--mix", default="dev", choices=["dev", "final"])
    r.add_argument("--mode", default=None, choices=["auto", "live", "replay", "fake"])
    r.add_argument("--planted", nargs="*", default=None, help="planted case ids, e.g. PP-STALE PP-CONFLICT")
    r.add_argument("--note", default="", help="optional free-text note about you and your situation")
    r.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = ap.parse_args(argv)

    preset = load_presets()[a.preset]
    planted = a.planted if a.planted is not None else preset.get("planted_cases", [])
    overrides = overrides_from_manifest(DEFAULT, planted) if planted else None
    mode = a.mode or DEFAULT.LLM_MODE
    if mode == "fake":
        from .fake_agents import fake_llm
        llm = fake_llm(DEFAULT, overrides)
    else:
        llm = LLM(DEFAULT, mode=mode)

    def show(ev):
        if ev["status"] in ("running", "pending"):
            return
        print(f"  [{ICON.get(ev['status'], '   ')}] {ev['step']:<9} #{ev['attempt']} {ev['headline']}", file=sys.stderr)

    try:
        profile = {**preset["profile"], "free_text": a.note} if a.note else preset["profile"]
        res = run(profile, overrides, on_event=show, llm=llm, mix=a.mix)
    except ProfileError as e:
        print("Profile problems:", *e.problems, sep="\n  ")
        return 2
    except LLMError as e:
        print("AI call problem:", e)
        return 3
    if a.json:
        print(json.dumps(res, indent=1, default=str))
        return 0
    rep = res["report"]
    print(f"\n{rep['fictional_notice']}\n")
    print(f"{rep.get('series', '')}  |  {rep['direction'].upper()}  {rep.get('timing_window', '')}")
    print(rep["summary_md"])
    if rep["caveats"]:
        print("Caveats:", *rep["caveats"], sep="\n  - ")
    print("\nSources:")
    for p in rep["provenance"]:
        print(f"  {p['source_id']} tier {p['tier']} updated {p['last_updated']} rows {p['rows_used']} "
              f"{p['status']} flags={p['flags']}")
    c = rep["cost"]
    print(f"\nRun cost: ${c['total_usd']:.4f} ({c['model_calls']} model calls, {c['paid_calls']} paid)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
