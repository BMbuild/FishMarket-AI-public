"""Scripted stand-ins for the three agents. They build schema-valid outputs from the inputs they are given,
so the whole pipeline can run for free. Used by tests and by the offline `--mode fake` demo."""
from __future__ import annotations

import json
from typing import Optional

import pandas as pd

from .config import Config, DEFAULT
from .llm import FakeLLM
from .loader import covers_series, load_all
from .registry import load_registry
from .schemas import Action, Claim, NumberRef, Profile, StatRow
from .templates import template_analysis, template_summary


def _coverage_oracle(cfg: Config, overrides):
    reg = load_registry(cfg, (overrides or {}).get("registry_path"))
    raws = load_all(cfg, reg, overrides)
    return reg, lambda sp, rg: [s for s in raws if covers_series(raws[s], sp, rg)]


def fake_llm(cfg: Config = DEFAULT, overrides: Optional[dict] = None, agent1_bad: set | None = None,
             agent1_always_wrong_source: bool = False, agent2_bad: set | None = None,
             summary_bad: bool = False) -> FakeLLM:
    """agent1_bad / agent2_bad: sets of 1-based attempt numbers that return a rule-breaking answer."""
    reg, oracle = _coverage_oracle(cfg, overrides)
    agent1_bad, agent2_bad = agent1_bad or set(), agent2_bad or set()

    def planner(system, user, schema, attempt):
        msg = json.loads(user)
        b = msg["request_brief"]
        if attempt in agent1_bad:
            return {"sources": ["SRC-NOPE"], "primary_source_id": "SRC-NOPE", "rationale": "scripted bad plan"}
        cov = [s for s in oracle(b["species"], b["region"]) if reg.loc[s, "trust_tier"] != "D"]
        if not cov:      # a generated series (scenario_species): the registry row in the message says what it covers
            cov = [r["source_id"] for r in msg.get("registry", []) if r["source_id"] == "SRC-GEN-01" and f"{b['species']}|{b['region']}" in str(r["covers"])]
        if agent1_always_wrong_source:
            cov = cov + ["SRC-SMP-01"]
        tier = {r["source_id"]: r["trust_tier"] for r in msg.get("registry", [])}
        primary = max(cov, key=lambda s: "DCBA".index(tier.get(s) or reg.loc[s, "trust_tier"])) if cov else ""
        return {"sources": cov, "primary_source_id": primary, "rationale": "All approved sources that cover it."}

    def analyst(system, user, schema, attempt):
        msg = json.loads(user)
        stats = [StatRow(**s) for s in msg["statistics"]]
        prof = Profile(**{**msg["profile"]})
        out = template_analysis(stats, prof, DEFAULT, with_lens=True, qtype=msg.get("question_type", "sell_or_hold"),
                                op_label=msg["profile"].get("operation", ""))
        if attempt in agent2_bad:
            out.claims[0] = Claim(id="C1", text="Prices will jump 99.9% next month.", stat_ids=[stats[0].id],
                                  numbers=[NumberRef(value=99.9, stat_id=stats[0].id)])
        return out.model_dump()

    def summarizer(system, user, schema, attempt):
        if summary_bad:
            return {"markdown": "Just sell it. Confidence: certain."}
        msg = json.loads(user)
        species = msg["market"].split(" in ")[0]
        claims = [Claim(id=c["id"], text=c["text"], stat_ids=[]) for c in msg["verified_claims"]]
        actions = [Action(text=t) for t in msg["actions"]]
        md = template_summary(msg["direction"], msg["timing_window"], species, claims, actions,
                              msg["confidence_rating"], msg["confidence_reasons"], msg["caveats"],
                              msg.get("question_type", "sell_or_hold"))
        if msg.get("recommendation"):
            import re
            md = re.sub(r"(## Recommendation\n)[^\n]*", lambda m: m.group(1) + msg["recommendation"], md, count=1)
        return {"markdown": md}

    return FakeLLM({"agent1": planner, "agent2": analyst, "summary": summarizer})


class StubAnthropicClient:
    """Looks like `anthropic.Anthropic()` for the one call we make, but answers from a FakeLLM's handlers.
    Lets tests exercise the real wrapper (cache, ledger, spend guard, pricing) without a network or a key."""

    _AGENT_BY_TOOL = {"submit_plan": "agent1", "submit_analysis": "agent2", "submit_summary": "summary"}
    # Like the real API: these models return a 400 for a forced tool_choice ("tool" or "any").
    REJECTS_FORCED_TOOL = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"}

    def __init__(self, fake: FakeLLM, in_tokens: int = 1500, out_tokens: int = 300, reject_temperature: bool = False):
        self.fake, self.in_tokens, self.out_tokens = fake, in_tokens, out_tokens
        self.reject_temperature = reject_temperature
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kw):
        from types import SimpleNamespace
        self.requests.append(kw)
        if self.reject_temperature and "temperature" in kw:
            raise ValueError("temperature: this model does not accept a temperature setting")
        if kw["model"] in self.REJECTS_FORCED_TOOL and kw["tool_choice"]["type"] in ("tool", "any"):
            raise ValueError('400 tool_choice: type "tool" and "any" are not supported for this model.')
        agent = self._AGENT_BY_TOOL[kw["tools"][0]["name"]]
        system = kw["system"] if isinstance(kw["system"], str) else kw["system"][0]["text"]
        attempt = 1 + sum(1 for x in self.fake.log if x["agent"] == agent)
        user = kw["messages"][0]["content"]
        out = self.fake.handlers[agent](system, user, kw["tools"][0], attempt)
        self.fake.log.append({"agent": agent, "attempt": attempt, "user": user})
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=out)],
                               usage=SimpleNamespace(input_tokens=self.in_tokens, output_tokens=self.out_tokens))
