"""Agent 2: the analyst (AI). The three lenses are prompt sections, not separate agents."""
from __future__ import annotations

import json

from pydantic import ValidationError

from ..config import Config
from ..schemas import AnalysisOutput, StatRow, tool_def
from . import load_prompt

ANALYSIS_TOOL = tool_def("submit_analysis", "Submit the analysis.", AnalysisOutput)


RULES = {
    "sell_or_hold": "direction is hold if best_next3_vs_now_ratio is at least the hold threshold row, otherwise sell_now",
    "buy_now_or_wait": "buy_now if next3_mean_vs_now_ratio is at least the buy threshold row, wait if at most the wait threshold row, otherwise no_clear_signal",
    "best_months": "ranking: the best_month_score rows, highest first, open-season months only",
    "compare_markets": "ranking: the market_net_price rows, highest first; markets with a market_age_days row were left out as out of date",
    "best_buyer_type": "ranking: the buyer_net_price rows, highest first",
}


def hold_economics(profile, stats: list[StatRow], flags, decision: dict | None) -> dict | None:
    """Python states whether the holding gain was calculated, so the analyst never has to decide it."""
    if profile.question_type != "sell_or_hold":
        return None
    row = next((s for s in stats if s.kind == "hold_net_gain_pct"), None)
    if row is not None:
        return {"status": "calculated", "stat_id": row.id}
    if (decision or {}).get("direction") == "sell_now":
        return {"status": "not calculated", "reason": "the rule says sell now"}
    if "no_storage_info" in flags:
        return {"status": "not calculated", "reason": "no storage given"}
    return {"status": "not calculated", "reason": "no holding cost data"}


def build_user(profile, stats: list[StatRow], trust: dict, flags: dict, cfg: Config,
               violations: list[str] | None = None, decision: dict | None = None, note_block: str | None = None,
               op_label: str = "", caveat_flags: list[str] | None = None, real_world: list[str] | None = None,
               situation: dict | None = None) -> str:
    msg = {
        "profile": {"region": profile.region, "operation": op_label or profile.business_type,
                    "business_type": profile.business_type,
                    "species": profile.species, "customer_segment": profile.customer_segment,
                    "volume_lb_per_month": profile.volume_lb_per_month, "storage": profile.storage,
                    "as_of": profile.as_of, "goal": profile.goal, "constraints": list(profile.constraints),
                    "experience": profile.experience},
        "question_type": profile.question_type,
        "statistics": [s.model_dump() for s in stats],
        "data_quality": {"confidence_rating": trust["rating"], "reasons": trust["reasons"],
                         "flags": sorted(flags)},
        "decision_rule": RULES.get(profile.question_type, RULES["sell_or_hold"]),
        "python_result": decision or {},
    }
    hold = hold_economics(profile, stats, flags, decision)
    if hold is not None:
        msg["hold_economics"] = hold
    if note_block:
        msg["user_note"] = note_block
    if real_world:
        msg["real_world_context"] = real_world
    sit = situation or {}
    if sit.get("note_facts"):
        msg["note_facts"] = sit["note_facts"]
    if sit.get("user_question"):
        msg["user_question"] = f"<user_question>{sit['user_question']}</user_question>"
    if violations:
        msg["fix_these_problems_from_your_previous_answer"] = violations
    return json.dumps(msg, indent=1, default=str)


def ask(llm, ctx, model: str, max_tokens: int, profile, stats, trust, flags, cfg, violations=None,
        decision=None, note_block=None, op_label="", real_world=None, situation=None):
    call = llm.call("agent2", load_prompt("agent2"),
                    build_user(profile, stats, trust, flags, cfg, violations, decision, note_block, op_label, real_world=real_world,
                               situation=situation),
                    ANALYSIS_TOOL, model, max_tokens, ctx)
    try:
        return AnalysisOutput.model_validate(call["tool_input"]), [], call
    except ValidationError as e:
        first = e.errors()[0]
        return None, [f"SHAPE: output did not match the required format at {'.'.join(map(str, first['loc']))}: "
                      f"{first['msg']}"], call
