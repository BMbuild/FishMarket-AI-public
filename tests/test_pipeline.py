import shutil
from dataclasses import replace

import pandas as pd
import pytest

from fishmarket import loader
from fishmarket.config import DEFAULT
from fishmarket.fake_agents import StubAnthropicClient, fake_llm
from fishmarket.llm import FakeLLM, LLM, LLMError
from fishmarket.pipeline import ProfileError, run
from fishmarket.templates import CAVEATS

PROFILE = {"region": "Gulf", "business_type": "wild_catch", "species": ["Gulf shrimp"],
           "customer_segment": "mainstream", "volume_lb_per_month": 40000, "as_of": "2026-10-15"}


def ev(res, step):
    return [e for e in res["events"] if e["step"] == step]


def statuses(res, step):
    return [e["status"] for e in ev(res, step)]


# ---- all 12 golden profiles with the scripted model ----------------------------------------------
@pytest.mark.parametrize("idx", range(12))
def test_golden_profiles_with_fake_model(idx, golden, cfg):
    g = golden[idx]
    ov = loader.overrides_from_manifest(DEFAULT, g["planted_cases"]) if g["planted_cases"] else None
    res = run(g["profile"], ov, llm=fake_llm(cfg, ov), cfg=cfg)
    e = g["expected"]
    assert res["status"] == "ok"
    assert res["analysis"]["direction"] == e["direction"], g["case_id"]
    assert res["trust"]["rating"] == e["expected_trust"], g["case_id"]
    assert set(e["required_gate_flags"]) <= set(res["flags"]), (g["case_id"], res["flags"])
    tags = set(res["analysis"]["driver_tags"])
    assert set(e["required_driver_tags"]) <= tags and not tags & set(e["forbidden_driver_tags"]), g["case_id"]
    assert res["calls"] <= 5 and "cautious_answer" not in res["flags"] and "template_summary" not in res["flags"]
    assert res["report"]["confidence"]["rating"] == e["expected_trust"]
    assert "Fictional" in res["report"]["fictional_notice"]


# ---- retry and fallback paths --------------------------------------------------------------------
def test_invalid_plan_is_retried_once(cfg):
    llm = fake_llm(cfg, agent1_bad={1})
    res = run(PROFILE, llm=llm, cfg=cfg)
    assert statuses(res, "agent1") == ["retrying", "done"] and res["calls"] == 4
    assert res["trust"]["rating"] == "high" and "python_default_plan" not in res["notes"]


def test_plan_invalid_twice_uses_python_default_plan(cfg):
    res = run(PROFILE, llm=fake_llm(cfg, agent1_bad={1, 2}), cfg=cfg)
    assert "python_default_plan" in res["notes"] and statuses(res, "agent1")[-1] == "fallback"
    assert res["calls"] == 4 and res["trust"]["rating"] == "high"
    assert res["gate"]["usable"] == ["SRC-GOV-01", "SRC-IND-01", "SRC-RTL-01", "SRC-TRD-01"]


def test_plan_policy_rejects_a_plan_that_adds_a_source_without_rows(cfg):
    res = run(PROFILE, llm=fake_llm(cfg, agent1_always_wrong_source=True), cfg=cfg)
    assert "python_default_plan" in res["notes"]
    assert any("SRC-SMP-01" in v or "Tier D" in v for v in ev(res, "agent1")[0]["detail"]["violations"])


def short_data_cfg(cfg, tmp_path):
    """A copy of the data in which every approved source has only 10 months for Gulf shrimp | Gulf,
    while the sample file still has its full 24 months."""
    dst = tmp_path / "data_copy"
    shutil.copytree(DEFAULT.DATA_DIR, dst, ignore=shutil.ignore_patterns("tests_only", "__pycache__"))
    for f in ("gov_landings", "assoc_wholesale", "trade_price_notes"):
        p = dst / "data" / f"{f}.csv"
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        m = (df.species == "Gulf shrimp") & (df.region == "Gulf")
        keep = df[m].sort_values("date").tail(10).index
        df.drop(df[m].index.difference(keep)).to_csv(p, index=False)
    return replace(cfg, DATA_DIR=dst)


def test_hard_failure_retries_agent1_once_then_falls_back_to_sample_data(cfg, tmp_path):
    c = short_data_cfg(cfg, tmp_path)
    llm = fake_llm(c)
    res = run(PROFILE, llm=llm, cfg=c)
    assert res["status"] == "ok"
    assert len([x for x in llm.log if x["agent"] == "agent1"]) == 2
    assert "fallback_sample_data" in res["flags"] and res["trust"]["rating"] == "low"
    assert CAVEATS["fallback_sample_data"] in res["report"]["caveats"]
    assert statuses(res, "gate") == ["warning", "warning", "fallback"]
    assert res["gate"]["primary_id"] == "SRC-SMP-01" and res["calls"] == 4


def test_hard_failure_skips_the_retry_when_both_agent1_calls_were_spent(cfg, tmp_path):
    c = short_data_cfg(cfg, tmp_path)
    llm = fake_llm(c, agent1_bad={1, 2})
    res = run(PROFILE, llm=llm, cfg=c)
    assert len([x for x in llm.log if x["agent"] == "agent1"]) == 2
    assert "fallback_sample_data" in res["flags"] and res["calls"] == 4


def test_worst_case_is_exactly_five_calls(cfg, tmp_path):
    c = short_data_cfg(cfg, tmp_path)
    res = run(PROFILE, llm=fake_llm(c, agent2_bad={1, 2}), cfg=c)
    assert res["calls"] == 5
    assert {"fallback_sample_data", "cautious_answer"} <= set(res["flags"])


def test_no_source_passes_at_all_is_a_clean_failure(cfg):
    c = replace(cfg, MIN_CLEAN_MONTHS=100)
    llm = fake_llm(c)
    res = run(PROFILE, llm=llm, cfg=c)
    assert res["status"] == "failed" and "no recommendation" in res["message"]
    assert [x["agent"] for x in llm.log] == ["agent1", "agent1"]


def test_grounding_failure_once_retries_agent2(cfg):
    llm = fake_llm(cfg, agent2_bad={1})
    res = run(PROFILE, llm=llm, cfg=cfg)
    assert statuses(res, "grounding") == ["retrying", "done"] and res["calls"] == 4
    assert "cautious_answer" not in res["flags"]
    retry_user = [x for x in llm.log if x["agent"] == "agent2"][1]["user"]
    assert "fix_these_problems_from_your_previous_answer" in retry_user and "Prices will jump" not in retry_user


def test_grounding_failure_twice_gives_the_cautious_answer(cfg):
    res = run(PROFILE, llm=fake_llm(cfg, agent2_bad={1, 2}), cfg=cfg)
    assert "cautious_answer" in res["flags"] and res["calls"] == 4
    assert CAVEATS["cautious_answer"] in res["report"]["caveats"]
    assert res["analysis"]["direction"] == "hold" and res["analysis"]["lens_notes"]["region"] == ""
    assert res["trust"]["rating"] == "high"          # confidence never comes from the model


def test_summary_check_failure_uses_the_template_without_retry(cfg):
    llm = fake_llm(cfg, summary_bad=True)
    res = run(PROFILE, llm=llm, cfg=cfg)
    assert "template_summary" in res["flags"] and res["calls"] == 3
    assert len([x for x in llm.log if x["agent"] == "summary"]) == 1
    assert res["report"]["summary_md"].count("## ") == 4 and "Confidence: high." in res["report"]["summary_md"]
    assert CAVEATS["template_summary"] in res["report"]["caveats"]


def test_summary_must_state_the_python_confidence(cfg):
    base = fake_llm(cfg)
    orig = base.handlers["summary"]

    def lies(system, user, schema, attempt):
        return {"markdown": orig(system, user, schema, attempt)["markdown"].replace("Confidence: high.", "Confidence: low.")}
    base.handlers["summary"] = lies
    res = run(PROFILE, llm=base, cfg=cfg)
    assert "template_summary" in res["flags"] and "Confidence: high." in res["report"]["summary_md"]


def test_api_failure_in_agent2_degrades_to_cautious_answer(cfg):
    llm = fake_llm(cfg)

    def boom(*a):
        raise LLMError("rate limited")
    llm.handlers["agent2"] = boom
    res = run(PROFILE, llm=llm, cfg=cfg)
    assert statuses(res, "agent2") == ["failed"] and "cautious_answer" in res["flags"]
    assert len([x for x in llm.log if x["agent"] == "agent2"]) == 0      # no retry loop on API errors


def test_api_failure_in_agent1_uses_default_plan_without_retry(cfg):
    llm = fake_llm(cfg)
    llm.handlers["agent1"] = lambda *a: (_ for _ in ()).throw(LLMError("network down"))
    res = run(PROFILE, llm=llm, cfg=cfg)
    assert "python_default_plan" in res["notes"] and statuses(res, "agent1")[0] == "failed"
    assert res["status"] == "ok"


# ---- profile validation --------------------------------------------------------------------------
@pytest.mark.parametrize("change,needle", [
    ({"species": ["Gulf shrimp", "Cod", "Catfish", "Tilapia"]}, "between 1 and 3 species"),
    ({"species": ["<script>alert(1)</script>"]}, "Species names may use"),
    ({"volume_lb_per_month": 0}, "greater than 0"),
    ({"region": "Atlantis"}, "region"),
    ({"as_of": "2026-13-45"}, "as_of"),
    ({"business_type": "pirate"}, "operation_type"),
    ({"customer_segment": "rich"}, "customer_segment"),
])
def test_profile_validation(change, needle, cfg):
    with pytest.raises(ProfileError) as e:
        run({**PROFILE, **change}, llm=fake_llm(cfg), cfg=cfg)
    assert needle in str(e.value)


# ---- caveats, provenance and events ---------------------------------------------------------------
def test_unit_case_shows_caveat_and_provenance(cfg):
    ov = loader.overrides_from_manifest(DEFAULT, ["PP-UNIT"])
    p = {**PROFILE, "region": "Northeast", "species": ["Cod"]}
    res = run(p, ov, llm=fake_llm(cfg, ov), cfg=cfg)
    r = res["report"]
    assert CAVEATS["unit_mismatch"] in r["caveats"] and res["trust"]["rating"] == "medium"
    row = next(x for x in r["provenance"] if x["source_id"] == "SRC-GOV-01")
    assert row["flags"]["unit_mismatch"] == 6 and row["status"] == "primary"


def test_g06_shows_conflict_and_stale_handling(golden, cfg):
    g = golden[5]
    ov = loader.overrides_from_manifest(DEFAULT, g["planted_cases"])
    r = run(g["profile"], ov, llm=fake_llm(cfg, ov), cfg=cfg)["report"]
    assert CAVEATS["source_disagreement"] in r["caveats"] and CAVEATS["stale_data"] in r["caveats"]
    assert any(p["status"].startswith("excluded: stale") for p in r["provenance"])


def test_events_stream_and_run_file(cfg):
    seen = []
    res = run(PROFILE, llm=fake_llm(cfg), cfg=cfg, on_event=seen.append)
    steps = ["profile", "agent1", "gate", "analytics", "agent2", "grounding", "summary", "report"]
    assert [e["step"] for e in seen[:8]] == steps and all(e["status"] == "pending" for e in seen[:8])
    assert {"running", "done"} <= {e["status"] for e in seen}
    assert [e["step"] for e in res["events"]] == steps
    assert (cfg.RUNS_DIR / f"{res['run_id']}.json").exists()


def test_pipeline_is_deterministic_for_the_same_inputs(cfg):
    a = run(PROFILE, llm=fake_llm(cfg), cfg=cfg, save=False)
    b = run(PROFILE, llm=fake_llm(cfg), cfg=cfg, save=False)
    assert a["report"]["summary_md"] == b["report"]["summary_md"] and a["stats"] == b["stats"]


# ---- the real wrapper end to end (stubbed SDK) -----------------------------------------------------
def test_auto_mode_second_run_costs_nothing_and_replay_matches(cfg):
    stub = StubAnthropicClient(fake_llm(cfg))
    first = run(PROFILE, llm=LLM(cfg, "auto", client=stub), cfg=cfg)
    assert first["paid_calls"] == 3 and first["report"]["cost"]["total_usd"] > 0
    second = run(PROFILE, llm=LLM(cfg, "auto", client=stub), cfg=cfg)
    assert second["paid_calls"] == 0 and second["report"]["cost"]["total_usd"] == 0.0
    replay = run(PROFILE, llm=LLM(cfg, "replay"), cfg=cfg)
    assert replay["report"]["summary_md"] == first["report"]["summary_md"]
    assert replay["report"]["cost"]["total_usd"] == 0.0


def test_replay_miss_degrades_gracefully_in_the_pipeline(cfg):
    res = run(PROFILE, llm=LLM(cfg, "replay"), cfg=cfg)
    assert res["status"] == "ok" and "python_default_plan" in res["notes"] and "cautious_answer" in res["flags"]
    assert "template_summary" in res["flags"] and res["report"]["cost"]["total_usd"] == 0.0
