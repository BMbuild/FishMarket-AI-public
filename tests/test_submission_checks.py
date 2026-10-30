"""Checks behind the submission plan: (1) sources without a usable date are flagged, never trusted; (2) the analyst
reads only data that passed the gate and can only return its one structured answer; (3) actions outside an agent's
permissions and missing permission lists are refused before anything is sent. No test touches the network."""
import pandas as pd
import pytest

from fishmarket import gate as G, loader, permissions
from fishmarket.agents import agent1, agent2, researcher, summary
from fishmarket.config import DEFAULT
from fishmarket.fake_agents import fake_llm
from fishmarket.llm import LLM, RunCtx
from fishmarket.pipeline import run
from fishmarket.registry import load_catalog, load_registry
from helpers import AS_OF
from test_web_research import HAIKU, WebStub, reply


# ---- (1) source dates ----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cod_source():
    reg = load_registry(DEFAULT)
    raws = loader.load_all(DEFAULT, reg, None)
    return raws["SRC-GOV-01"], reg.loc["SRC-GOV-01"], load_catalog(DEFAULT)


def _gate_with(cod_source, **changes):
    raw, row, cat = cod_source
    row = row.copy()
    for k, v in changes.items():
        row[k] = v
    return G.gate_source(raw, row, "Cod", "Northeast", DEFAULT, AS_OF, cat)


def test_a_dated_source_is_still_usable(cod_source):
    assert _gate_with(cod_source).usable


@pytest.mark.parametrize("blank", [None, "", float("nan"), "not a date"])
def test_a_source_with_no_last_updated_date_is_excluded_as_stale(cod_source, blank):
    """Freshness that cannot be proved is treated as stale, not as fresh."""
    r = _gate_with(cod_source, last_updated=blank)
    assert not r.usable and r.flags.get("stale_data") == 1
    assert "last-updated date" in r.excluded_reason


@pytest.mark.parametrize("blank", [None, "", float("nan"), 0, -5])
def test_a_source_with_no_update_cadence_is_excluded_as_stale(cod_source, blank):
    r = _gate_with(cod_source, update_cadence_days=blank)
    assert not r.usable and r.flags.get("stale_data") == 1
    assert "update cadence" in r.excluded_reason


# ---- (2) the analyst reads validated data only ----------------------------------------------------
def test_the_analyst_has_one_answer_tool_and_no_web():
    p = permissions.policy("agent2")
    assert p.tools == frozenset({agent2.ANALYSIS_TOOL["name"]}) and not p.web and p.max_searches_per_run == 0


def test_the_analyst_never_sees_statistics_from_an_excluded_source(cfg):
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-STALE"])
    profile = {"region": "Northeast", "business_type": "wild_catch", "species": ["Cod"],
               "customer_segment": "mainstream", "volume_lb_per_month": 20000, "as_of": "2026-10-15"}
    llm = fake_llm(cfg, ov)
    res = run(profile, ov, llm=llm, cfg=cfg)
    assert res["status"] == "ok" and "stale_data" in res["flags"]
    analytics = next(e for e in res["events"] if e["step"] == "analytics")
    used = {s["source_id"] for s in analytics["detail"]["stats"]}
    assert used and "SRC-IND-01" not in used


# ---- (3) refusals ---------------------------------------------------------------------------------
@pytest.mark.parametrize("agent,tool", [
    ("agent2", agent1.PLAN_TOOL), ("agent2", summary.SUMMARY_TOOL),
    ("summary", agent2.ANALYSIS_TOOL), ("agent1", summary.SUMMARY_TOOL),
    ("coordinator", agent2.ANALYSIS_TOOL), ("", agent2.ANALYSIS_TOOL),
])
def test_an_agent_outside_its_tools_is_refused_before_anything_is_sent(cfg, agent, tool):
    stub = WebStub([])
    llm = LLM(cfg, mode="live", client=stub)
    with pytest.raises(permissions.PermissionDenied):
        llm.call(agent, "s", "u", tool, HAIKU, 500, RunCtx())
    assert stub.requests == []


def test_a_request_with_no_tool_is_refused(cfg):
    llm = LLM(cfg, mode="live", client=WebStub([]))
    for tool in (None, {}):
        with pytest.raises(permissions.PermissionDenied):
            llm.call("agent2", "s", "u", tool, HAIKU, 500, RunCtx())


def test_the_analyst_call_limit_is_enforced(cfg):
    p, usage = permissions.policy("agent2"), permissions.Usage()
    for _ in range(p.max_calls_per_run):
        permissions.check_call("agent2", agent2.ANALYSIS_TOOL, 500, 0.0, usage)
    with pytest.raises(permissions.PermissionDenied):
        permissions.check_call("agent2", agent2.ANALYSIS_TOOL, 500, 0.0, usage)


@pytest.mark.parametrize("missing", ["TRUSTED_FILE", "BLOCKED_FILE"])
def test_a_missing_site_list_never_opens_the_web(cfg, monkeypatch, tmp_path, missing):
    """No trusted list: no search at all. No blocked list: no open-web search. Both fail closed."""
    monkeypatch.setenv("FISHMARKET_LOG_MISSES", "0")
    monkeypatch.setattr(permissions, missing, tmp_path / "absent.txt")
    stub = WebStub([reply([])])              # one empty trusted-site answer at most; a second request would fail
    out = researcher.research("How many seafood processing plants operate in Ohio?",
                              LLM(cfg, mode="live", client=stub), cfg)
    assert len(stub.requests) == (0 if missing == "TRUSTED_FILE" else 1)
    assert all(r["tools"][0].get("allowed_domains") for r in stub.requests)     # never an open-web request
    assert out["facts"] == [] and out["error"]
