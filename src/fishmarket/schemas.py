"""Pydantic schemas shared across the pipeline."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Profile(BaseModel):
    region: str
    business_type: str            # the operation id (from registry/operation_types.csv); also exposed as operation_type
    species: list[str]
    customer_segment: str
    volume_lb_per_month: float
    as_of: str
    question_type: str = "sell_or_hold"
    question: str = "Should I sell now or hold over the next 3 months?"
    storage: str = "none"         # none | chilled | frozen
    free_text: str = ""           # the user's own note (sanitised before use; untrusted)
    experience: str = ""
    goal: str = ""
    constraints: list[str] = Field(default_factory=list)
    own_question: str = ""        # a question the user typed instead of (or as well as) picking one; untrusted
    question_matched: bool = True # False when own_question did not match any calculation (the default one ran)

    @property
    def operation_type(self) -> str:
        return self.business_type


class RequestBrief(BaseModel):
    profile: Profile
    species: str
    region: str
    series: str            # "species|region" for the first species
    question: str
    all_species: list[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    sources: list[str]
    primary_source_id: str
    rationale: str = ""


class StatRow(BaseModel):
    id: str
    series: str
    kind: str
    value: Optional[float]
    unit: str
    label: str = ""
    month: Optional[str] = None
    reliability: Optional[str] = None
    window: str = ""
    source_id: str = ""
    n_obs: int = 0


class NumberRef(BaseModel):
    value: float
    stat_id: str


class Claim(BaseModel):
    id: str
    text: str
    stat_ids: list[str] = Field(default_factory=list)
    numbers: list[NumberRef] = Field(default_factory=list)


class Action(BaseModel):
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class LensNotes(BaseModel):
    region: str = ""
    business_type: str = ""
    customer: str = ""
    your_situation: str = ""      # the user's goal, constraints, note and own question


class AnalysisOutput(BaseModel):
    direction: Literal["hold", "sell_now", "buy_now", "wait", "no_clear_signal", "ranking", "per_species", "insufficient_data"]
    timing_window: str = ""
    headline: str = ""
    claims: list[Claim]
    driver_tags: list[str] = Field(default_factory=list)
    actions: list[Action]
    lens_notes: LensNotes = Field(default_factory=LensNotes)


class SummaryOutput(BaseModel):
    markdown: str


def tool_def(name: str, description: str, model: type[BaseModel]) -> dict:
    """Anthropic tool definition built from a pydantic model."""
    schema = model.model_json_schema()
    schema.pop("title", None)
    # driver tags are derived by Python (rule), never asked of the model
    schema.get("properties", {}).pop("driver_tags", None)
    if "driver_tags" in schema.get("required", []):
        schema["required"].remove("driver_tags")
    return {"name": name, "description": description, "input_schema": schema}
