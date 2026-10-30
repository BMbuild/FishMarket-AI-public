"""Four live runs of G01 on p4 (runs 56e82070e7, 750ea85506, 8155b83abc, ec5854b02f; Haiku 5.5 and Sonnet 5.5)
failed grounding on the first try 4 times out of 4, and 3 ended in the cautious answer. The causes were not
fabrications. Each test below reproduces one of them with the models' own wording."""
from decimal import Decimal

import pytest

from fishmarket.agents import load_prompt
from fishmarket.analytics import compute_stats
from fishmarket.fake_agents import fake_llm
from fishmarket.grounding import check_analysis, numerals_in
from fishmarket.pipeline import run
from fishmarket.schemas import Claim, NumberRef
from fishmarket.templates import template_analysis
from helpers import AS_OF, gate_series

G01 = {"region": "Gulf", "species": ["Gulf shrimp"], "customer_segment": "mainstream", "volume_lb_per_month": 40000,
       "as_of": "2026-10-15", "operation_type": "wild_catch", "question_type": "sell_or_hold"}


@pytest.fixture(scope="module")
def stats():
    g, _ = gate_series("Gulf shrimp", "Gulf")
    return compute_stats(g.clean, "Gulf shrimp|Gulf", g.primary_id, AS_OF)["stats"]


def kind(stats, k):
    return next(s for s in stats if s.kind == k)


@pytest.fixture
def good(stats):
    a = template_analysis(stats, None, with_lens=False)
    assert check_analysis(a, stats) == []
    return a


# ---- cause 1: the number is right, but the model did not list it in `numbers` ---------------------------

def test_undeclared_number_equal_to_a_cited_statistic_is_accepted(good, stats):
    r = kind(stats, "best_next3_vs_now_ratio")
    good.claims[0] = Claim(id="C1", text="The best of the next three months is about 1.20 times this month's level.",
                           stat_ids=[r.id], numbers=[])
    assert check_analysis(good, stats) == []


def test_undeclared_number_that_matches_no_cited_statistic_is_still_rejected(good, stats):
    r = kind(stats, "best_next3_vs_now_ratio")
    good.claims[0] = Claim(id="C1", text="The best of the next three months is about 1.35 times this month's level.",
                           stat_ids=[r.id], numbers=[])
    assert any(v.startswith("G2") and "1.35" in v for v in check_analysis(good, stats))


def test_undeclared_number_equal_to_an_uncited_statistic_is_still_rejected(good, stats):
    now = kind(stats, "seasonal_index_now")
    good.claims[0] = Claim(id="C1", text="The best of the next three months is about 1.20 times this month's level.",
                           stat_ids=[now.id], numbers=[])
    assert any(v.startswith("G2") and "1.20" in v for v in check_analysis(good, stats))


def test_a_wrongly_declared_value_is_still_rejected(good, stats):
    """Sonnet 5.5 declared 12.0 for the year-over-year change to get past a '12 calendar months' numeral."""
    y = kind(stats, "yoy_price_change_pct")
    good.claims[0] = Claim(id="C1", text="Prices changed 12% over the year.", stat_ids=[y.id],
                           numbers=[NumberRef(value=12.0, stat_id=y.id)])
    assert any(v.startswith("G2") for v in check_analysis(good, stats))


# ---- cause 2: a true number from the user's own profile --------------------------------------------------

def test_profile_volume_is_accepted_outside_the_claims(good, stats):
    good.actions[0].text = "As a wild-catch fisher with 40000 lb per month, hold part of the catch toward January."
    assert check_analysis(good, stats, profile_numbers={Decimal("40000")}) == []


def test_a_volume_the_user_did_not_give_is_still_rejected(good, stats):
    good.actions[0].text = "As a wild-catch fisher with 55000 lb per month, hold part of the catch toward January."
    assert any("55000" in v for v in check_analysis(good, stats, profile_numbers={Decimal("40000")}))


# ---- cause 4: window lengths are not quantities ---------------------------------------------------------

@pytest.mark.parametrize("text", ["over the latest 12 calendar months", "the 12-month average", "for 3 months"])
def test_window_lengths_are_not_numbers_to_ground(text):
    assert numerals_in(text) == []


def test_days_are_still_checked():
    assert numerals_in("a median freshness of 10 days") == [Decimal("10")]


# ---- cause 3: hold_economics is a note, not a statistic --------------------------------------------------

def test_prompt_says_hold_economics_is_not_a_stat_id():
    assert "never put hold_economics in stat_ids" in load_prompt("agent2")


# ---- end to end: the same habits no longer force the cautious answer --------------------------------------

def test_pipeline_accepts_an_analyst_that_writes_cited_numbers_without_listing_them(cfg):
    fake = fake_llm(cfg)
    honest = fake.handlers["agent2"]

    def live_like(system, user, schema, attempt):
        out = honest(system, user, schema, attempt)
        for c in out["claims"]:
            c["numbers"] = []                               # the habit seen in 3 of 4 live runs
        out["actions"][0]["text"] += " With 40000 lb per month, stagger sales."
        return out

    fake.handlers["agent2"] = live_like
    res = run(G01, llm=fake, cfg=cfg, save=False)
    assert "cautious_answer" not in res["flags"]
    assert not any(e["step"] == "grounding" and e["status"] == "retrying" for e in res["events"])


# ---- cause 1b: numbers taken from a cited statistic's own window or observation count ---------------------

def test_number_from_a_cited_statistics_window_is_accepted(good, stats):
    """Sonnet 5.5 copied 'the 12 before' from S5's window, 'latest 12 months vs the 12 before'."""
    y = kind(stats, "yoy_price_change_pct")
    assert "12 before" in y.window
    good.claims[0] = Claim(id="C1", text=f"Prices over the latest 12 months against the 12 before changed "
                                         f"{abs(y.value):.2f} percent.", stat_ids=[y.id], numbers=[])
    assert check_analysis(good, stats) == []


def test_observation_count_of_a_cited_statistic_is_accepted(good, stats):
    y = kind(stats, "yoy_price_change_pct")
    good.claims[0] = Claim(id="C1", text=f"Across {y.n_obs} monthly prices the change was {abs(y.value):.2f} percent.",
                           stat_ids=[y.id], numbers=[])
    assert check_analysis(good, stats) == []


def test_a_count_that_matches_nothing_cited_is_still_rejected(good, stats):
    y = kind(stats, "yoy_price_change_pct")
    good.claims[0] = Claim(id="C1", text=f"Across {y.n_obs + 7} monthly prices the change was {abs(y.value):.2f} percent.",
                           stat_ids=[y.id], numbers=[])
    assert any(v.startswith("G2") and str(y.n_obs + 7) in v for v in check_analysis(good, stats))
