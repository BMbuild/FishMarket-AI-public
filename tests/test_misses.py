from dataclasses import replace
from pathlib import Path

import pytest

from fishmarket import real_data
from fishmarket.config import DEFAULT
from fishmarket.qa import answer, misses
from fishmarket.qa.context import Context

pytestmark = pytest.mark.skipif(not real_data.DEFAULT_CSV.exists(), reason="NOAA csv missing")


def test_misses_are_logged_and_summarised(tmp_path, monkeypatch):
    cfg = replace(DEFAULT, RUNS_DIR=tmp_path)
    monkeypatch.setenv("FISHMARKET_LOG_MISSES", "1")
    monkeypatch.setattr(misses, "DEFAULT", cfg)
    ctx = Context.load(Path("/nonexistent-lake"), live=False)
    answer.ask("What is the price of unicorn steak?", ctx)
    answer.ask("Tell me a joke about the stock market", ctx)
    answer.ask("What is the dockside price of American lobster?", ctx)            # answered: not logged
    rows = misses.path(cfg).read_text().splitlines()
    assert len(rows) == 2
    s = misses.summary(cfg)
    assert "2 unanswered" in s and "tell me a joke about the stock market" in s


def test_logging_can_be_turned_off(tmp_path, monkeypatch):
    cfg = replace(DEFAULT, RUNS_DIR=tmp_path)
    monkeypatch.setattr(misses, "DEFAULT", cfg)
    monkeypatch.setenv("FISHMARKET_LOG_MISSES", "0")
    answer.ask("Tell me a joke", Context.load(Path("/nonexistent-lake"), live=False))
    assert not misses.path(cfg).exists()
