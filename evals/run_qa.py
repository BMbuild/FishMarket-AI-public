"""Runs evals/qa_benchmark.yaml through the engine (rule-based, no paid calls) and reports accuracy and safety counts.
Usage: PYTHONPATH=src python evals/run_qa.py [--lake DIR]"""
import argparse
import sys
import time
from pathlib import Path

import yaml

from fishmarket.qa import answer
from fishmarket.qa.context import Context

ap = argparse.ArgumentParser()
ap.add_argument("--lake", default=None, help="lake dir; default builds the labelled TEST FIXTURE lake in a temp dir")
args = ap.parse_args()
if args.lake is None:
    import tempfile
    from fishmarket import gbif
    tmp = tempfile.mkdtemp()
    gbif.build(Path(__file__).resolve().parents[1] / "tests/fixtures/gbif_test_fixture.tsv.gz", Path(tmp), is_test_fixture=True, built_at="2026-01-01T00:00:00")
    args.lake = tmp
ctx = Context.load(Path(args.lake))
rows = yaml.safe_load((Path(__file__).with_name("qa_benchmark.yaml")).read_text())
fails, t0 = [], time.time()
n_verdict = n_entry = n_entry_total = n_cite = n_cite_total = ground = mixed = 0
for r in rows:
    try:
        a = answer.ask(r["q"], ctx)
    except Exception as e:  # any crash is a failure
        fails.append((r["q"], f"crash: {e}")); continue
    ok = a["verdict"] in r["verdicts"]
    n_verdict += ok
    if r["entry"] not in (None, "*"):
        n_entry_total += 1; n_entry += a["entry_id"] == r["entry"]
    if a["verdict"] in ("answered", "partly") and a["entry_id"]:
        n_cite_total += 1; n_cite += bool(a["citations"]) and bool(a["claims"])
    low = a["answer_md"].lower()
    if any(f.lower() in low for f in r.get("forbid", [])):
        ground += 1; fails.append((r["q"], "forbidden text"))
    if len(set(a.get("origins", [])) & {"REAL (NOAA)", "SYNTHETIC"}) > 1 and a["entry_id"] != "market_compare":
        mixed += 1
    if not ok: fails.append((r["q"], f"verdict {a['verdict']} not in {r['verdicts']}"))
    elif r["entry"] not in (None, "*") and a["entry_id"] != r["entry"]:
        fails.append((r["q"], f"entry {a['entry_id']} != {r['entry']}"))
N = len(rows)
print(f"questions {N}  verdict accuracy {n_verdict/N:.1%}  entry accuracy {n_entry/max(1,n_entry_total):.1%}  "
      f"citation completeness {n_cite/max(1,n_cite_total):.1%}  forbidden-text hits {ground}  origin mixing {mixed}  "
      f"{(time.time()-t0)/N*1000:.0f} ms/question  cost $0.00")
for f in fails[:25]: print(" -", f)
sys.exit(1 if (ground or mixed or n_verdict / N < 0.9) else 0)
