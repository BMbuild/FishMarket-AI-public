"""Stage status contract (idea from Brahim's draft). Complements handoff.py, which validates NOAA observations. A FLAGGED record may never feed a confirmed analysis,
and must say why and what to do next. Maps onto the gate: gate warnings -> WARNING, hard blocks -> FLAGGED."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, model_validator

Stage = Literal["collection", "price_analysis", "quality_analysis"]


class StageHandoff(BaseModel):
    stage: Stage
    status: Literal["OK", "WARNING", "FLAGGED"]
    payload: dict
    flag_reason: Optional[str] = None
    required_action: Optional[str] = None

    @model_validator(mode="after")
    def flagged_needs_reason(self):
        if self.status == "FLAGGED" and not (self.flag_reason and self.required_action):
            raise ValueError("FLAGGED records need both flag_reason and required_action")
        return self


class FlaggedRecordError(Exception):
    pass


def ensure_confirmable(handoffs: list[StageHandoff]) -> None:
    """Call before building a confirmed analysis."""
    bad = [h for h in handoffs if h.status == "FLAGGED"]
    if bad:
        raise FlaggedRecordError("; ".join(f"{h.stage}: {h.flag_reason}" for h in bad))
