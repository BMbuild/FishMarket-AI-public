"""Agent 1: retrieval planner (AI) plus the Python plan policy that checks it."""
from __future__ import annotations

import json

import pandas as pd
from pydantic import ValidationError

from ..registry import TIER_RANK
from ..schemas import PlanOutput, RequestBrief, tool_def
from . import load_prompt

PLAN_TOOL = tool_def("submit_plan", "Submit the list of data sources to query.", PlanOutput)
REGISTRY_FIELDS = ["source_id", "trust_tier", "covers", "has_volume", "price_basis", "last_updated", "notes"]


def build_user(brief: RequestBrief, registry: pd.DataFrame, problems: list[str] | None = None) -> str:
    rows = []
    for _, r in registry.iterrows():
        row = {k: r[k] for k in REGISTRY_FIELDS}
        row["has_volume"] = bool(row["has_volume"])
        row["last_updated"] = str(pd.Timestamp(row["last_updated"]).date())
        rows.append(row)
    msg = {"request_brief": {"species": brief.species, "region": brief.region,
                             "business_type": brief.profile.business_type, "question": brief.question},
           "registry": rows}
    if problems:
        msg["problems_with_your_previous_plan"] = problems
    return json.dumps(msg, indent=1, default=str)


def check_plan(plan: PlanOutput, registry: pd.DataFrame, covering: list[str]) -> list[str]:
    """Plan policy. `covering` = source ids whose files really contain the series."""
    v = []
    unknown = [s for s in plan.sources if s not in registry.index]
    if unknown:
        v.append(f"Unknown source ids: {unknown}.")
    chosen = [s for s in plan.sources if s in registry.index]
    for s in chosen:
        if s not in covering:
            v.append(f"{s} has no rows for this species and region; remove it.")
    abc = [s for s in covering if registry.loc[s, "trust_tier"] in ("A", "B", "C")]
    for s in abc:
        if s not in chosen:
            v.append(f"{s} covers this series and is tier {registry.loc[s, 'trust_tier']}; "
                     "every A, B and C source that covers it must be included.")
    if abc and any(registry.loc[s, "trust_tier"] == "D" for s in chosen):
        v.append("Tier D sample data may only be used when no other source covers the series.")
    if not chosen:
        v.append("The plan chose no sources.")
    elif plan.primary_source_id not in chosen:
        v.append("primary_source_id must be one of the chosen sources.")
    else:
        best = max(TIER_RANK[registry.loc[s, "trust_tier"]] for s in chosen)
        if TIER_RANK[registry.loc[plan.primary_source_id, "trust_tier"]] != best:
            v.append("primary_source_id must be the highest-tier chosen source.")
    return v


def default_plan(registry: pd.DataFrame, covering: list[str]) -> PlanOutput:
    pick = [s for s in registry.index if s in covering and registry.loc[s, "trust_tier"] in ("A", "B", "C")]
    if not pick:
        pick = [s for s in registry.index if s in covering]
    primary = max(pick, key=lambda s: TIER_RANK[registry.loc[s, "trust_tier"]]) if pick else ""
    return PlanOutput(sources=pick, primary_source_id=primary, rationale="Deterministic default plan.")


def ask(llm, ctx, model: str, max_tokens: int, brief, registry, problems=None):
    """Returns (plan or None, schema_problems, call_result)."""
    call = llm.call("agent1", load_prompt("agent1"), build_user(brief, registry, problems), PLAN_TOOL,
                    model, max_tokens, ctx)
    try:
        return PlanOutput.model_validate(call["tool_input"]), [], call
    except ValidationError as e:
        return None, [f"The plan did not match the required format: {e.errors()[0]['msg']}"], call
