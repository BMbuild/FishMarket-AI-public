"""Log of questions the Ask engine could not answer, so the wiki and question types grow from what people really ask.
Stored locally in runs/qa_misses.jsonl (gitignored). Turn off with FISHMARKET_LOG_MISSES=0.
Summary:  python -m fishmarket.qa.misses"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

from ..config import DEFAULT
from ..llm import _now          # timestamps live in llm.py/events.py only (the app's no-clock rule)

MISS_VERDICTS = ("cannot", "clarify")


def path(cfg=None) -> Path:
    return Path((cfg or DEFAULT).RUNS_DIR) / "qa_misses.jsonl"


def enabled() -> bool:
    return os.environ.get("FISHMARKET_LOG_MISSES", "1").strip().lower() not in ("0", "false", "no")


def record(question: str, result: dict, cfg=None) -> None:
    """Appends one line when an answer is a refusal or a clarifying question (or one part of a compound question was)."""
    if not enabled():
        return
    parts = result.get("parts") or [result]
    missed = [r for r in parts if r.get("verdict") in MISS_VERDICTS]
    if not missed:
        return
    row = {"ts": _now(), "question": question[:300], "verdict": result.get("verdict"),
           "entry_id": result.get("entry_id"), "missed_parts": len(missed),
           "reason": (missed[0].get("answer_md") or "")[:160]}
    try:
        p = path(cfg)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass                                    # logging must never break an answer


def summary(cfg=None, top: int = 25) -> str:
    p = path(cfg)
    if not p.exists():
        return "No unanswered questions logged yet."
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_v = Counter(r["verdict"] for r in rows)
    by_reason = Counter((r.get("reason") or "")[:70] for r in rows)
    qs = Counter(r["question"].strip().lower() for r in rows)
    out = [f"{len(rows)} unanswered or unclear questions logged ({', '.join(f'{k} {v}' for k, v in by_v.items())}).", "",
           "Most common reasons:"] + [f"  {n:>3}  {r}" for r, n in by_reason.most_common(8)] + ["", "Questions (most asked first):"] + \
          [f"  {n:>3}  {q}" for q, n in qs.most_common(top)]
    return "\n".join(out)


if __name__ == "__main__":
    print(summary())
    sys.exit(0)
