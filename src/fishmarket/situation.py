"""The user's own situation in the scenario: their typed question, free goals and constraints, and the facts
Python read out of their note. Everything here is Python; models only see the results, as untrusted text.

- match_question: a typed question goes to the nearest of the five calculations (question_cues.csv).
- clean_items: free-text goals and constraints, cleaned and checked for instruction-like text.
- merge: what the note adds to the form (constraints, goal, experience) and where it disagrees with it.
- notes: plain sentences, written by Python from the result, that connect the answer to the user's situation.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import note as note_mod

MAX_ITEM = 80
MAX_ITEMS = 6


@lru_cache(maxsize=2)
def _question_cues(data_dir: str) -> list[tuple[str, re.Pattern]]:
    out = []
    with open(Path(data_dir) / "registry" / "question_cues.csv", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#") or line.startswith("question_type,"):
                continue
            qt, pat = line.split(",", 1)
            out.append((qt, re.compile(pat, re.I)))
    return out


def match_question(text: str, allowed: list[str], data_dir) -> str | None:
    """The calculation a typed question is closest to, among those the operation may ask, or None."""
    for qt, rx in _question_cues(str(data_dir)):
        if qt in allowed and rx.search(text or ""):
            return qt
    return None


def clean_items(items, max_chars: int = MAX_ITEM) -> tuple[list[str], list[str]]:
    """(kept, dropped_as_instructions). Each item is cleaned like the note; instruction-like items are dropped."""
    if isinstance(items, str):
        items = [x for x in re.split(r"[;\n]", items)]
    kept, dropped = [], []
    for it in items or []:
        t = note_mod.sanitise(str(it), max_chars)["text"]
        if not t:
            continue
        if note_mod.matched_injection(t):
            dropped.append(t)
            continue
        if t.lower() not in (k.lower() for k in kept):
            kept.append(t)
    return kept[:MAX_ITEMS], dropped


def merge(prof, facts: dict) -> tuple[dict, list[str]]:
    """Fields the note fills in (only where the form left them empty), and plain lines on where note and form differ."""
    upd, differs = {}, []
    cons = list(prof.constraints)
    for c in facts.get("constraints", []):
        if c.lower() not in (x.lower() for x in cons):
            cons.append(c)
    if cons != list(prof.constraints):
        upd["constraints"] = cons[:MAX_ITEMS]
    if facts.get("goal") and not prof.goal:
        upd["goal"] = facts["goal"]
    if facts.get("experience") and not prof.experience:
        upd["experience"] = facts["experience"]
    if facts.get("storage") and facts["storage"] != prof.storage:
        differs.append(f"your note suggests storage '{facts['storage']}' but the form says '{prof.storage}'")
    if facts.get("segment") and facts["segment"] != prof.customer_segment:
        differs.append(f"your note suggests {facts['segment'].replace('_', ' ')} customers but the form says {prof.customer_segment.replace('_', ' ')}")
    if facts.get("volume_lb_per_month") and abs(facts["volume_lb_per_month"] - prof.volume_lb_per_month) > 0.25 * prof.volume_lb_per_month:
        differs.append("your note gives a different monthly volume from the form")
    return upd, differs


def agent_facts(facts: dict) -> list[str]:
    """What the note says, for the agents, without any number from the note."""
    out = []
    if facts.get("species"):
        out.append("species mentioned: " + ", ".join(facts["species"]))
    if facts.get("storage"):
        out.append("storage: " + {"none": "no storage", "frozen": "has a freezer", "chilled": "chilled or live holding"}[facts["storage"]])
    if facts.get("segment"):
        out.append("customers: " + facts["segment"].replace("_", " "))
    if facts.get("asks"):
        out.append("also asked about: " + ", ".join(facts["asks"]))
    return out


def notes(prof, direction: str, window: str, qtype: str, trust: str, tables: dict, facts: dict) -> list[str]:
    """Python's own sentences tying the result to the user's goal, constraints and note. No new numbers except
    months the user gave and months Python computed."""
    out = []
    cons = {c.lower() for c in prof.constraints}
    hold = tables.get("hold") or {}
    if direction == "hold":
        if "cash needed soon" in cons:
            out.append(f"You said you need cash soon. Holding means no income from this product until you sell ({window}).")
        if "limited storage" in cons or prof.storage == "none":
            out.append("Holding needs storage, and you said yours is limited or that you have none.")
        sm = facts.get("storage_months")
        if sm and hold.get("months") and hold["months"] > sm:
            out.append(f"Your note says you can store for about {sm:g} months, but the best month is {hold['months']} months away.")
        if prof.goal == "steady income":
            out.append("Your goal is steady income; holding moves this product's sales later in the year.")
    if direction == "sell_now" and prof.goal == "maximize price":
        out.append("Your goal is the best price, and the data does not show a better price in the next three months.")
    if qtype in ("compare_markets", "best_buyer_type") and "single buyer" in cons:
        out.append("You said you sell to one buyer; this ranking shows what other buyers or markets pay, for comparison.")
    if qtype == "best_months" and "seasonal workers" in cons:
        out.append("Check that the best months line up with when your seasonal crew is available.")
    if trust == "low" and prof.goal == "reduce risk":
        out.append("Your goal is lower risk, and confidence in these figures is low, so treat them as a rough guide.")
    return out
