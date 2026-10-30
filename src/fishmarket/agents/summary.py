"""Summary agent (AI, small model). Never retried: a failed check falls back to the template."""
from __future__ import annotations

import json

from pydantic import ValidationError

from ..schemas import SummaryOutput, tool_def
from . import load_prompt

SUMMARY_TOOL = tool_def("submit_summary", "Submit the one-page summary as markdown.", SummaryOutput)


def build_user(species: str, region: str, direction: str, window: str, claims, actions, trust: dict,
               caveats: list[str], question_type: str = "sell_or_hold", note_block: str | None = None,
               op_label: str = "", headline: str = "", recommendation: str = "", real_world: list[str] | None = None,
               situation: dict | None = None) -> str:
    extra = {"user_note": note_block} if note_block else {}
    if real_world:
        extra["real_world_context"] = real_world
    sit = situation or {}
    if sit.get("goal") or sit.get("constraints"):
        extra["your_situation"] = {"goal": sit.get("goal", ""), "constraints": sit.get("constraints", [])}
    if sit.get("lens_note"):
        extra["situation_note"] = sit["lens_note"]
    return json.dumps({
        **extra,
        "market": f"{species} in {region}", "question_type": question_type, "operation": op_label,
        "recommendation": recommendation, "headline": headline,
        "direction": direction, "timing_window": window,
        "verified_claims": [{"id": c.id, "text": c.text} for c in claims],
        "actions": [a.text for a in actions],
        "confidence_rating": trust["rating"], "confidence_reasons": trust["reasons"],
        "caveats": caveats}, indent=1)


def ask(llm, ctx, model: str, max_tokens: int, user: str):
    call = llm.call("summary", load_prompt("summary"), user, SUMMARY_TOOL, model, max_tokens, ctx)
    try:
        return SummaryOutput.model_validate(call["tool_input"]).markdown, call
    except ValidationError:
        return "", call
