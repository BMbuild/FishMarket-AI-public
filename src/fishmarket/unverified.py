"""Shows an AI explanation that failed its checks next to the verified answer, with a disclaimer.
The verified (rule-based) answer always stays the main answer; this is extra reading, clearly marked.
Some failures are never shown: copied instruction-like text (G8) and a direction that contradicts the rules (G3),
because showing those would mislead or repeat an injection attempt."""
from __future__ import annotations

import re

DISCLAIMER = ("Not verified: this explanation from the AI analyst failed one or more automatic checks, so some numbers "
              "or statements in it may be wrong. Rely on the verified answer above; read this only as extra context.")
PLAIN = {"G1": "a claim does not cite a computed statistic", "G2": "a number does not match the computed statistics",
         "G5": "an action does not point to a claim", "G6": "it names a seasonal peak the data cannot support",
         "SHAPE": "the answer is missing parts"}
NEVER_SHOW = ("G3", "G8")


def code(v: str) -> str:
    return v.split(":", 1)[0].strip()


def showable(violations: list[str]) -> bool:
    return bool(violations) and not any(code(v) in NEVER_SHOW for v in violations)


def _claim_ids(v: str) -> set[str]:
    return set(re.findall(r"\bclaim (\w+)\b", v))


def build(analysis, violations: list[str]) -> dict | None:
    """Rejected analysis -> display block, or None when it must not be shown."""
    if analysis is None or not showable(violations):
        return None
    bad = set().union(*[_claim_ids(v) for v in violations]) if violations else set()
    a = analysis.model_dump() if hasattr(analysis, "model_dump") else dict(analysis)
    claims = [{"text": c.get("text", ""), "failed_check": c.get("id") in bad} for c in a.get("claims", [])]
    problems = list(dict.fromkeys(PLAIN.get(code(v), "it failed an automatic check") for v in violations))
    return {"disclaimer": DISCLAIMER, "headline": a.get("headline", ""), "claims": claims, "problems": problems,
            "details": violations}
