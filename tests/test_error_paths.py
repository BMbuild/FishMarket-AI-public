"""Lot 4 of the reliability audit: end-to-end error paths. Whatever fails, the run finishes with a labelled
answer, every problem is visible in the trace and the caveats, and no secret or silent skip slips through."""
import json
from dataclasses import replace

import pandas as pd
import pytest

from fishmarket import loader
from fishmarket.config import DEFAULT
from fishmarket.fake_agents import StubAnthropicClient, fake_llm
from fishmarket.llm import LLM, LLMError
from fishmarket.pipeline import run
from fishmarket.registry import load_registry
from fishmarket.report import FICTIONAL_LINE
from fishmarket.templates import CAVEAT_ORDER, CAVEATS

G01 = {"region": "Gulf", "species": ["Gulf shrimp"], "customer_segment": "mainstream", "volume_lb_per_month": 40000,
       "as_of": "2026-10-15", "operation_type": "wild_catch", "question_type": "sell_or_hold"}
TWO = {"operation_type": "inshore_boat", "region": "Mid-Atlantic", "species": ["Striped bass", "Summer flounder"],
       "customer_segment": "mainstream", "volume_lb_per_month": 15000}
STATUSES = {"pending", "running", "done", "warning", "retrying", "failed", "fallback"}


# ---- 15. a species that could not be checked is named, never dropped silently ----------------------

def _short_history(tmp_path, species, region, months=12):
    """Overrides that leave `species|region` with only `months` months in every source that covers it."""
    reg = load_registry(DEFAULT)
    raws = loader.load_all(DEFAULT, reg, None)
    files = {}
    for sid, d in raws.items():
        m = (d["species"] == species) & (d["region"] == region)
        if not m.any():
            continue
        keep = d[m].sort_values("date").tail(months)
        out = tmp_path / f"{sid}.csv"
        pd.concat([d[~m], keep]).to_csv(out, index=False)
        files[sid] = str(out)
    return {"source_files": files}


def test_skipped_species_is_named_in_the_caveats_and_summary(cfg, tmp_path):
    ov = _short_history(tmp_path, "Summer flounder", "Mid-Atlantic")
    res = run(TWO, ov, llm=fake_llm(cfg, ov), cfg=cfg, save=False)
    assert res["status"] == "ok"
    assert list(res["gates"]) == ["Striped bass"]
    assert "species_skipped" in res["flags"]
    sentence = "Summer flounder could not be checked against enough verified data, so it has no answer here."
    assert sentence in res["report"]["caveats"]
    assert sentence in res["report"]["summary_md"]
    assert any(e["step"] == "gate" and "Summer flounder" in e["headline"] and e["status"] == "warning"
               for e in res["events"])


def test_no_species_skipped_flag_when_every_species_is_answered(cfg):
    res = run(TWO, llm=fake_llm(cfg), cfg=cfg, save=False)
    assert "species_skipped" not in res["flags"] and len(res["gates"]) == 2


# ---- the budget guard stops a run part-way, visibly ------------------------------------------------

def test_per_run_budget_reached_mid_run_degrades_visibly(cfg):
    tight = replace(cfg, PER_RUN_LIMIT_USD=0.001)
    llm = LLM(tight, mode="live", client=StubAnthropicClient(fake_llm(tight)))
    res = run(G01, llm=llm, cfg=tight, save=False)
    assert res["status"] == "ok" and res["paid_calls"] == 1
    blocked = [e for e in res["events"] if e["step"] == "agent2" and e["status"] == "failed"]
    assert blocked and "limit" in blocked[0]["headline"]
    assert {"cautious_answer", "template_summary"} <= set(res["flags"])
    assert res["report"]["cost"]["total_usd"] <= tight.PER_RUN_LIMIT_USD


# ---- every AI step failing still gives a labelled, rule-based answer --------------------------------

def test_all_three_agents_failing_still_gives_a_labelled_answer(cfg):
    llm = fake_llm(cfg)
    for agent in ("agent1", "agent2", "summary"):
        llm.handlers[agent] = lambda *a: (_ for _ in ()).throw(LLMError("service unavailable"))
    res = run(G01, llm=llm, cfg=cfg, save=False)
    assert res["status"] == "ok" and res["calls"] <= 5
    assert "python_default_plan" in res["notes"]
    assert {"cautious_answer", "template_summary"} <= set(res["flags"])
    rep = res["report"]
    assert rep["fictional_notice"] == FICTIONAL_LINE
    assert rep["confidence"] == res["trust"]
    assert CAVEATS["cautious_answer"] in rep["caveats"] and CAVEATS["template_summary"] in rep["caveats"]
    assert rep["direction"] == "hold"            # the rule still decides


# ---- secrets in error messages never reach the trace, the saved run or the ledger -------------------

def test_key_in_an_sdk_error_is_redacted_everywhere(cfg):
    secret = "sk-" + "ant-api03-" + "ABCDEFGHIJKLMNOPQRST"     # built at runtime so the repo key scan stays clean

    class Leaky:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            raise RuntimeError(f"401 invalid x-api-key {secret}")

    res = run(G01, llm=LLM(cfg, mode="live", client=Leaky()), cfg=cfg, save=True)
    assert res["status"] == "ok"
    blobs = [json.dumps(res, default=str), open(res["saved_to"]).read()]
    if cfg.LEDGER_PATH.exists():
        blobs.append(cfg.LEDGER_PATH.read_text())
    assert not any(secret[:16] in b for b in blobs)
    assert any("[redacted]" in e["headline"] for e in res["events"])


# ---- invariants over every golden run --------------------------------------------------------------

@pytest.mark.parametrize("idx", range(53))
def test_every_flag_is_explained_and_every_problem_is_visible(idx, golden, cfg):
    g = golden[idx]
    ov = loader.overrides_from_manifest(DEFAULT, g["planted_cases"]) if g["planted_cases"] else None
    res = run(g["profile"], ov, llm=fake_llm(cfg, ov), cfg=cfg, save=False)
    rep = res["report"]
    for f in set(res["flags"]) & set(CAVEAT_ORDER):
        assert CAVEATS[f] in rep["caveats"], f
    assert rep["fictional_notice"] == FICTIONAL_LINE
    assert rep["confidence"]["rating"] == res["trust"]["rating"]
    for e in res["events"]:
        assert e["status"] in STATUSES
        if e["status"] in {"warning", "retrying", "failed", "fallback"}:
            assert e["headline"] and e["headline"] != "Working...", e
    assert rep["cost"]["total_usd"] == pytest.approx(sum(e["cost_usd"] for e in res["events"]))
