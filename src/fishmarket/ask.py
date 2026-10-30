"""Command line: python -m fishmarket.ask "Is Atlantic cod moving north?" [--real-only] [--ai] [--lake DIR]"""
import argparse
import sys
from pathlib import Path

from .qa.answer import ask
from .qa.context import Context


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fishmarket.ask")
    ap.add_argument("question")
    ap.add_argument("--lake", type=Path, default=None)
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--real-only", action="store_true")
    ap.add_argument("--ai", action="store_true", help="use the AI planner and summary (uses saved answers first)")
    a = ap.parse_args(argv)
    ctx = Context.load(a.lake, a.csv, real_only=a.real_only)
    llm = None
    if a.ai:
        from .llm import LLM
        from .config import DEFAULT
        llm = LLM(DEFAULT, mode="auto")
    r = ask(a.question, ctx, llm=llm)
    print(f"[{r['verdict'].upper()}]  entry={r['entry_id']}  confidence={r['confidence']}  origins={', '.join(r['origins']) or '-'}\n")
    print(r["answer_md"])
    if r["confidence_reasons"]:
        print("\nConfidence: " + " ".join(r["confidence_reasons"]))
    if r["citations"]:
        print("\nCitations:\n- " + "\n- ".join(r["citations"]))
    if a.ai:
        how = "AI summary" if r.get("source") == "ai" else "template (AI not used" + (f": {r['source_reason']}" if r.get("source_reason") else "") + ")"
        print(f"\nAnswer written by: {how}; AI cost ${r.get('cost_usd', 0):.4f}")
    if r["flags"]:
        print("\nFlags:", ", ".join(r["flags"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
