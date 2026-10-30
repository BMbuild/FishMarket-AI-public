"""Run trace: one event per step and attempt, updated in place so the UI can render live."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

STEPS = ["profile", "agent1", "gate", "analytics", "agent2", "grounding", "summary", "report"]
AI_STEPS = {"agent1", "agent2", "summary"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Tracer:
    def __init__(self, run_id: Optional[str] = None, on_event: Optional[Callable[[dict], None]] = None):
        self.run_id = run_id or uuid.uuid4().hex[:10]
        self.on_event = on_event
        self.events: list[dict] = []

    def _push(self, ev: dict) -> None:
        if self.on_event:
            self.on_event(dict(ev))

    def begin(self, step: str, attempt: int = 1, headline: str = "") -> dict:
        ev = {"run_id": self.run_id, "step": step, "status": "running", "attempt": attempt,
              "started_at": _now(), "ended_at": None, "headline": headline or "Working...", "detail": {},
              "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "cache": None}
        self.events.append(ev)
        self._push(ev)
        return ev

    def finish(self, ev: dict, status: str, headline: str, detail: Optional[dict] = None,
               call: Optional[dict] = None) -> dict:
        ev.update(status=status, headline=headline, ended_at=_now())
        if detail is not None:
            ev["detail"] = detail
        if call:
            ev["tokens_in"] = call.get("usage", {}).get("input_tokens", 0)
            ev["tokens_out"] = call.get("usage", {}).get("output_tokens", 0)
            ev["cost_usd"] = call.get("cost_usd", 0.0)
            ev["cache"] = call.get("cache")
            if call.get("notes"):
                ev["detail"] = {**ev["detail"], "llm_notes": list(call["notes"])}
        self._push(ev)
        return ev

    def pending(self) -> None:
        """Announce all steps as pending so a UI can draw the eight cards up front."""
        for s in STEPS:
            self._push({"run_id": self.run_id, "step": s, "status": "pending", "attempt": 0, "headline": "",
                        "detail": {}, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "cache": None})

    def total_cost(self) -> float:
        return round(sum(e["cost_usd"] for e in self.events), 6)
