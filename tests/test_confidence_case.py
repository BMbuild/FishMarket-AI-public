"""Found in the first live trace (runs/ddb78b8eba.json, G01): a sound summary was thrown away and replaced by
the template only because the model wrote "Confidence: High." where the check wanted "Confidence: high."
Capitalisation is not a different rating; a different rating is still rejected."""
import pytest

from fishmarket.fake_agents import fake_llm
from fishmarket.pipeline import run
from fishmarket.schemas import Claim
from fishmarket.templates import check_summary

CLAIMS = [Claim(id="C1", text="Prices are seasonally low now.", stat_ids=["S1"])]


def _md(sure: str) -> str:
    return ("## Recommendation\nHold.\n\n## Why\n- a\n- b\n- c\n\n## What to do\n- x\n- y\n\n"
            f"## How sure we are\n{sure} The sources we checked agree.")


@pytest.mark.parametrize("sure", ["Confidence: high.", "Confidence: High.", "CONFIDENCE: HIGH.", "confidence: High."])
def test_capitalisation_of_the_confidence_line_is_accepted(sure):
    assert check_summary(_md(sure), "high", CLAIMS) == []


@pytest.mark.parametrize("sure", ["Confidence: Medium.", "Confidence: low.", "Confidence: very high.", "Confidence high."])
def test_a_different_or_malformed_rating_is_still_rejected(sure):
    assert any("Confidence" in p for p in check_summary(_md(sure), "high", CLAIMS))


def test_pipeline_keeps_a_summary_that_only_capitalises_the_rating(cfg):
    fake = fake_llm(cfg)
    honest = fake.handlers["summary"]

    def capitalising(system, user, schema, attempt):
        md = honest(system, user, schema, attempt)["markdown"]
        return {"markdown": md.replace("Confidence: high.", "Confidence: High.")}

    fake.handlers["summary"] = capitalising
    profile = {"region": "Gulf", "species": ["Gulf shrimp"], "customer_segment": "mainstream",
               "volume_lb_per_month": 40000, "as_of": "2026-10-15", "operation_type": "wild_catch",
               "question_type": "sell_or_hold"}
    res = run(profile, llm=fake, cfg=cfg, save=False)
    assert res["trust"]["rating"] == "high"
    assert "template_summary" not in res["flags"]
    assert "Confidence: High." in res["report"]["summary_md"]
