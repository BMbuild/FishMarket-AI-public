"""Lot 1 of the reliability audit: every number and every direction a user can read must be checked,
not only the claim text. Covers the analyst -> report handoff and the summary -> report handoff."""
import pytest

from fishmarket.analytics import compute_stats
from fishmarket.grounding import check_analysis, numerals_in
from fishmarket.pipeline import run
from fishmarket.fake_agents import fake_llm
from fishmarket.templates import (CAVEATS, check_summary, recommendation_sentence, template_analysis,
                                  template_summary)
from helpers import AS_OF, gate_series


@pytest.fixture(scope="module")
def shrimp():
    g, _ = gate_series("Gulf shrimp", "Gulf")
    return compute_stats(g.clean, "Gulf shrimp|Gulf", g.primary_id, AS_OF)["stats"]


@pytest.fixture
def good(shrimp):
    a = template_analysis(shrimp, None, with_lens=False)
    assert a.direction == "hold", "these tests assume the shrimp series says hold"
    assert check_analysis(a, shrimp) == []
    return a


# ---- numbers outside the claims (headline, actions, lens notes, timing window) -------------------

def test_number_in_headline_is_rejected(good, shrimp):
    good.headline = "Prices will jump 45% by December."
    assert any(v.startswith("G2") and "headline" in v and "45" in v for v in check_analysis(good, shrimp))


def test_number_in_action_is_rejected(good, shrimp):
    good.actions[0].text = "Hold until the price reaches $19.99 per lb."
    assert any(v.startswith("G2") and "action 1" in v and "19.99" in v for v in check_analysis(good, shrimp))


def test_number_in_lens_note_is_rejected(good, shrimp):
    good.lens_notes.region = "Gulf buyers pay 30% more in winter."
    assert any(v.startswith("G2") and "lens note" in v and "30" in v for v in check_analysis(good, shrimp))


def test_number_in_timing_window_is_rejected(good, shrimp):
    good.timing_window = "for 45 days"
    assert any(v.startswith("G2") and "timing window" in v for v in check_analysis(good, shrimp))


def test_month_only_timing_window_is_accepted(good, shrimp):
    good.timing_window = "over the next 3 months, through December"
    assert check_analysis(good, shrimp) == []


def test_verified_claim_number_may_be_repeated_outside_the_claims(good, shrimp):
    declared = next(n for c in good.claims for n in c.numbers)
    text = next(c.text for c in good.claims if declared in c.numbers)
    shown = next(str(x) for x in numerals_in(text))
    good.headline = f"Hold: the best coming month is about {shown} times this month."
    assert check_analysis(good, shrimp) == []


# ---- every action must rest on a verified claim (G5) ---------------------------------------------

def test_action_without_a_claim_is_rejected(good, shrimp):
    good.actions[0].claim_ids = []
    assert any(v.startswith("G5") and "action 1" in v for v in check_analysis(good, shrimp))


# ---- the numeral pattern -------------------------------------------------------------------------

def test_numeral_glued_to_a_lowercase_letter_is_caught():
    assert numerals_in("prices could rise x1.5 soon") == [pytest.approx(1.5)]
    assert numerals_in("about ~2.5 times") == [pytest.approx(2.5)]


def test_ids_are_still_not_numerals():
    assert numerals_in("see S3, C12 and Q4") == []


# ---- direction stated outside the direction field -----------------------------------------------

@pytest.mark.parametrize("field,text", [
    ("headline", "Sell now while prices hold up."),
    ("action", "Sell right away to lock in today's price."),
])
def test_text_contradicting_the_direction_is_rejected(good, shrimp, field, text):
    if field == "headline":
        good.headline = text
    else:
        good.actions[0].text = text
    assert any(v.startswith("G3") for v in check_analysis(good, shrimp))


# ---- the summary must keep Python's recommendation ------------------------------------------------

def _summary(good, shrimp, rec=None, todo=None):
    md = template_summary(good.direction, good.timing_window, "Gulf shrimp", good.claims, good.actions, "high",
                          ["Several approved sources were checked and agree."], [], "sell_or_hold", shrimp)
    if rec is not None:
        md = md.replace(_rec(good, shrimp), rec)
    if todo is not None:
        md = md.replace("## What to do\n", f"## What to do\n- {todo}\n")
    return md


def _rec(good, shrimp):
    return recommendation_sentence(good.direction, "sell_or_hold", "Gulf shrimp", good.timing_window, shrimp)


def test_template_summary_passes(good, shrimp):
    assert check_summary(_summary(good, shrimp), "high", good.claims, (), _rec(good, shrimp), good.direction) == []


def test_summary_with_a_different_recommendation_is_rejected(good, shrimp):
    md = _summary(good, shrimp, rec="Sell your Gulf shrimp now.")
    problems = check_summary(md, "high", good.claims, (), _rec(good, shrimp), good.direction)
    assert any("recommendation" in p.lower() for p in problems)


def test_summary_contradicting_the_direction_elsewhere_is_rejected(good, shrimp):
    md = _summary(good, shrimp, todo="Sell everything now, do not hold.")
    problems = check_summary(md, "high", good.claims, (), _rec(good, shrimp), good.direction)
    assert any("contradicts" in p for p in problems)


def test_pipeline_replaces_a_contradicting_summary_with_the_template(cfg):
    fake = fake_llm(cfg)
    honest = fake.handlers["summary"]

    def contrarian(system, user, schema, attempt):
        md = honest(system, user, schema, attempt)["markdown"]
        rec = md.split("## Recommendation\n", 1)[1].split("\n", 1)[0]
        return {"markdown": md.replace(rec, "Sell your Gulf shrimp now.")}

    fake.handlers["summary"] = contrarian
    profile = {"region": "Gulf", "species": ["Gulf shrimp"], "customer_segment": "mainstream",
               "volume_lb_per_month": 40000, "as_of": "2026-10-15", "operation_type": "wild_catch",
               "question_type": "sell_or_hold"}
    res = run(profile, llm=fake, cfg=cfg, save=False)
    assert res["analysis"]["direction"] == "hold"
    assert "template_summary" in res["flags"]
    assert CAVEATS["template_summary"] in res["report"]["caveats"]
    assert "Sell your Gulf shrimp now." not in res["report"]["summary_md"]
