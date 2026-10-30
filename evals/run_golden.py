"""Level 3 golden evaluation.

    python -m evals.run_golden --mix dev|final --mode fake|auto|live|replay [--cases G01,G02] [--yes]

Defaults to fake (free). A mode that can call the API (auto, live) runs only when named on the command line.

Scores the 53 golden cases automatically and writes evals/results/<timestamp>-<PROMPT_VERSION>-<mix>.json.
Reads fishmarket_data/tests_only/ on purpose: evaluation is the one place that may."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fishmarket.config import DEFAULT, PROMPT_VERSION  # noqa: E402
from fishmarket.llm import LLM  # noqa: E402
from fishmarket.loader import overrides_from_manifest  # noqa: E402
from fishmarket.pipeline import run  # noqa: E402

_OLD_KIND_GROUPS = {
    "seasonal_price_index": {"seasonal_index_now", "seasonal_index_best_next3", "best_next3_vs_now_ratio",
                             "seasonal_peak_month"},
    "yoy_price_change": {"yoy_price_change_pct"},
    "supply_yoy_change": {"supply_yoy_change_pct"},
}
# Rough expected cost of one case, used only for the "more than $1" confirmation guard.
EXPECTED_CASE_COST = {"dev": 0.004, "final": 0.035}


def score_case(case: dict, res: dict, model_inputs: list | None = None) -> dict:
    """Python-side expectations (golden_checks) plus live-model checks: citations and grounding behaviour."""
    from evals.golden_checks import check_case
    problems = check_case(case, res, model_inputs)
    checks = {"golden_expectations": not problems}
    if res["status"] != "ok":
        return {"passed": False, "checks": checks, "problems": problems, "cost_usd": 0.0}
    e = case["expected"]
    stats = {s["id"]: s for s in res["stats"]}
    cited = {sid for c in res["analysis"]["claims"] for sid in c["stat_ids"] if sid in stats}
    if "min_cited_stats" in e:
        checks["cited_stats"] = len(cited) >= e["min_cited_stats"]
    ev, cost = res["events"], res["report"]["cost"]
    return {"passed": all(checks.values()), "checks": checks, "problems": problems,
            "grounding_retries": sum(1 for x in ev if x["step"] == "grounding" and x["status"] == "retrying"),
            "agent1_calls": sum(1 for x in ev if x["step"] == "agent1" and x["status"] != "fallback"),
            "fallbacks": sorted(set(res["flags"]) & {"cautious_answer", "template_summary", "fallback_sample_data"})
            + (["python_default_plan"] if "python_default_plan" in res["notes"] else []),
            "tokens_in": sum(x["tokens_in"] for x in ev), "tokens_out": sum(x["tokens_out"] for x in ev),
            "cost_usd": cost["total_usd"], "model_calls": cost["model_calls"], "paid_calls": cost["paid_calls"]}


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mix", default="dev", choices=["dev", "final"])
    ap.add_argument("--mode", default="fake", choices=["fake", "auto", "live", "replay"],
                    help="fake (default) is free; auto and live can spend, so they must be named")
    ap.add_argument("--cases", default="", help="comma-separated, e.g. G01,G02")
    ap.add_argument("--yes", action="store_true", help="allow a live final run expected to cost more than $1")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)

    golden = json.loads((DEFAULT.DATA_DIR / "tests_only" / "golden_cases.json").read_text())
    want = {c.strip() for c in a.cases.split(",") if c.strip()}
    cases = [g for g in golden if not want or g["case_id"] in want]
    if not cases:
        print("No matching cases."); return 2
    est = EXPECTED_CASE_COST[a.mix] * len(cases)
    if a.mode == "live" and a.mix == "final" and est > 1.0 and not a.yes:
        print(f"Expected cost about ${est:.2f} (more than $1). Pass --yes to go ahead."); return 2

    llm = None if a.mode == "fake" else LLM(DEFAULT, mode=a.mode)
    rows, total = [], 0.0
    for g in cases:
        ov = overrides_from_manifest(DEFAULT, g["planted_cases"]) if g["planted_cases"] else None
        if a.mode == "fake":
            from fishmarket.fake_agents import fake_llm
            llm = fake_llm(DEFAULT, ov)
        try:
            res = run(g["profile"], ov, llm=llm, mix=a.mix, save=False)
            sc = score_case(g, res, [x["user"] for x in getattr(llm, "log", [])])
        except Exception as ex:                       # a failed case must not stop the whole pass
            sc = {"passed": False, "checks": {"run_ok": False}, "problems": [f"{type(ex).__name__}: {ex}"],
                  "cost_usd": 0.0}
        sc["case_id"], sc["name"] = g["case_id"], g["name"]
        total += sc.get("cost_usd", 0.0)
        rows.append(sc)
        bad = [k for k, v in sc["checks"].items() if not v]
        print(f"{g['case_id']}  {'PASS' if sc['passed'] else 'FAIL'}  ${sc.get('cost_usd', 0):.4f}  "
              f"{'' if sc['passed'] else 'failed: ' + ', '.join(bad)}")
    passed = sum(r["passed"] for r in rows)
    summary = {"prompt_version": PROMPT_VERSION, "mix": a.mix, "mode": a.mode, "cases": len(rows),
               "passed": passed, "total_cost_usd": round(total, 6),
               "ledger_total_usd": round(LLM(DEFAULT, mode="replay").ledger.total(), 6) if a.mode != "fake" else None}
    out = ROOT / "evals" / "results"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"{stamp}-{PROMPT_VERSION}-{a.mix}.json"
    path.write_text(json.dumps({"summary": summary, "cases": rows}, indent=1))
    print(f"\n{passed}/{len(rows)} passed, cost ${total:.4f}. Wrote {path.relative_to(ROOT)}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
