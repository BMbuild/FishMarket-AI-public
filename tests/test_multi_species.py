from pathlib import Path

import pytest

from fishmarket import real_data
from fishmarket.qa import answer, router
from fishmarket.qa.context import Context

pytestmark = pytest.mark.skipif(not real_data.DEFAULT_CSV.exists(), reason="NOAA csv missing")


@pytest.fixture(scope="module")
def ctx():
    return Context.load(Path("/nonexistent-lake"), live=False)


def test_three_way_compare_uses_one_common_year(ctx):
    a = answer.ask("Compare the price of American lobster, haddock and Atlantic cod", ctx)
    assert a["entry_id"] == "compare_species" and "all 3 species" in a["answer_md"]
    for sp in ("American lobster", "Haddock", "Atlantic cod"):
        assert sp in a["answer_md"]


def test_mismatched_latest_years_are_not_compared(ctx):
    a = answer.ask("Which is more expensive, Dungeness crab or snow crab?", ctx)
    assert "in 2022, the latest year all 2 species have data" in a["answer_md"]
    assert any("not compared with older years" in c for c in a["caveats"])


def test_landings_comparison_and_species_alias_not_a_region(ctx):
    p = router.plan("Compare landings of Pacific cod and Alaska pollock", ctx)
    assert p.species == ["Pacific cod", "Walleye pollock"] and p.region is None
    a = answer.ask("Compare landings of Pacific cod and Alaska pollock", ctx)
    assert "million lb" in a["answer_md"] and "per lb" not in a["answer_md"]


def test_shared_head_noun_list(ctx):
    assert router.plan("What are the prices of sockeye, chinook and coho salmon?", ctx).species == ["Sockeye salmon", "Chinook salmon", "Coho salmon"]


def test_single_species_types_fan_out_without_mixing(ctx):
    a = answer.ask("Are pink salmon and chum salmon overfished?", ctx)
    one, two = a["answer_md"].split("**2. Chum salmon**")
    assert "Pink salmon: stock status" in one and "Chum salmon: stock status" not in one
    assert "Chum salmon: stock status" in two
    b = answer.ask("Which states land the most Dungeness crab and blue crab?", ctx)
    assert "Washington" in b["answer_md"] and "Louisiana" in b["answer_md"]


def test_no_generic_definition_for_a_named_species_without_a_note(ctx):
    a = answer.ask("Is Atlantic salmon overfished?", ctx)
    assert a["verdict"] == "cannot" and "no stock-status or rules note for Atlantic salmon" in a["answer_md"]


@pytest.mark.parametrize("q", ["What is the price of salmon in Norway?", "What do Japanese buyers pay for bluefin tuna?", "What is the world price of shrimp?"])
def test_other_countries_markets_are_out_of_scope(ctx, q):
    a = answer.ask(q, ctx)
    assert a["verdict"] == "cannot" and "U.S. markets only" in a["answer_md"]


def test_other_countries_still_allowed_for_farming_and_trade(ctx):
    assert router.plan("How much Atlantic salmon does Norway farm?", ctx).scope == ""
    assert router.plan("Where do imported shrimp come from?", ctx).scope == ""
