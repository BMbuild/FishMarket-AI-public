from pathlib import Path

import pytest

from fishmarket import real_data, real_summary
from fishmarket.qa import answer
from fishmarket.qa.context import Context

CL = [{"id": "A", "text": "The 2024 dockside price was $6.35 per lb, +21.0% compared with 2023."}]


def test_judgment_words_are_rejected():
    ok, why = real_summary.grounded("Lobster prices rose sharply to $6.35 per lb, +21.0%.", CL)
    assert not ok and "judgment" in why
    assert real_summary.grounded("The price was $6.35 per lb, +21.0% on 2023.", CL)[0]


pytestmark = pytest.mark.skipif(not real_data.DEFAULT_CSV.exists(), reason="NOAA csv missing")


def test_inflation_answer_is_not_labelled_as_wiki_sourced():
    a = answer.ask("Has the American lobster price kept up with inflation?", Context.load(Path("/nonexistent-lake")))
    assert not any("short notes on public" in r for r in a["confidence_reasons"])


def test_ai_failure_is_reported_not_hidden():
    class Broken:
        mode = "auto"

        def call(self, *a, **k):
            raise RuntimeError("no service")
    a = answer.ask("Has the American lobster price kept up with inflation?", Context.load(Path("/nonexistent-lake")), llm=Broken())
    assert a["source"] == "template" and "AI unavailable" in a["source_reason"]
