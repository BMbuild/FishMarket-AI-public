import re
from pathlib import Path

import pytest

from fishmarket import real_data, wiki
from fishmarket.qa import answer, catalogue, router
from fishmarket.qa.context import Context


def test_wiki_file_is_valid_and_small():
    assert wiki.validate() == []
    es = wiki.load().values()
    assert 15 <= len(es) <= 60
    assert sum(len(e.text.split()) for e in es) < 4500          # stays a short text wiki, not a bloated one


def test_every_entry_has_a_real_source_link_and_date():
    for e in wiki.load().values():
        assert e.sources and all(s.startswith("https://") for s in e.sources)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.retrieved)


def test_validator_catches_bad_entries():
    bad = wiki.parse("## Bad Id | Title\ntype: nonsense\nkeywords: x\nretrieved: yesterday\nsource: http://insecure\nshort text\n")
    errs = " ".join(wiki.validate(bad))
    for frag in ("lowercase", "type must", "https source", "YYYY-MM-DD", "words"):
        assert frag in errs


@pytest.mark.parametrize("q,eid", [
    ("What does ex-vessel mean?", "ex_vessel"),
    ("What is a catch share?", "catch_shares"),
    ("How cold should tuna be kept?", "histamine"),
    ("How is recreational catch estimated?", "mrip"),
    ("Is Atlantic cod overfished?", "stock_atlantic_cod"),
    ("Is Pacific halibut overfished?", "stock_pacific_halibut"),
])
def test_search_finds_the_right_entry(q, eid):
    assert wiki.search(q)[0][1].id == eid


def test_unrelated_text_matches_nothing():
    assert wiki.search("tell me a joke about elephants") == []


def test_stock_entry_needs_a_status_word_not_just_the_species():
    assert wiki.search("What is the price of lobster?", ["American lobster"]) == []


pytestmark_noaa = pytest.mark.skipif(not real_data.DEFAULT_CSV.exists(), reason="NOAA csv missing")


@pytest.fixture(scope="module")
def ctx():
    return Context.load(Path("/nonexistent-lake"))


@pytestmark_noaa
def test_wiki_answers_are_cited_and_labelled(ctx):
    a = answer.ask("Is Atlantic cod overfished?", ctx)
    assert a["entry_id"] == "wiki_lookup" and a["verdict"] == "answered"
    assert "overfished and subject to overfishing" in a["answer_md"]
    assert a["confidence"] == "Medium"
    assert any("fisheries.noaa.gov/species/atlantic-cod" in c for c in a["citations"])
    assert a["origins"] == ["REAL (other public source)"]


@pytestmark_noaa
def test_data_questions_still_go_to_noaa(ctx):
    assert answer.ask("What is the dockside price of American lobster?", ctx)["entry_id"] == "price_history"
    assert answer.ask("What is the price difference between American lobster and haddock?", ctx)["entry_id"] == "compare_species"
    assert answer.ask("Has the American lobster price kept up with inflation?", ctx)["entry_id"] == "price_vs_inflation"


@pytestmark_noaa
def test_off_topic_is_still_refused(ctx):
    assert answer.ask("Tell me a joke about the stock market", ctx)["verdict"] == "cannot"
    assert answer.ask("What is the weather in Boston?", ctx)["verdict"] == "cannot"


@pytestmark_noaa
def test_wiki_never_mixes_with_synthetic(ctx):
    a = answer.ask("What does ex-vessel mean?", ctx)
    assert "SYNTHETIC" not in " ".join(a["origins"])


def test_catalogue_has_wiki_entry():
    assert "wiki_lookup" in catalogue.load()


def test_stale_entries_are_listed_relative_to_a_given_date():
    es = list(wiki.load().values())
    assert wiki.stale("2026-11-01", entries=es) == []
    assert len(wiki.stale("2030-01-01", entries=es)) == len(es)
