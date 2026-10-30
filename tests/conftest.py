import json
from dataclasses import replace

import pandas as pd
import pytest

from fishmarket import loader, registry
from fishmarket.config import DEFAULT, ROOT

DATA = ROOT / "fishmarket_data"


@pytest.fixture
def cfg(tmp_path):
    """Default settings, with every writable location redirected to a temp folder."""
    return replace(DEFAULT, CACHE_DIR=tmp_path / "cache", LEDGER_PATH=tmp_path / "ledger.jsonl",
                   RUNS_DIR=tmp_path / "runs", LLM_MODE="auto")


@pytest.fixture(scope="session")
def reg():
    return registry.load_registry(DEFAULT)


@pytest.fixture(scope="session")
def catalog():
    return registry.load_catalog(DEFAULT)


@pytest.fixture(scope="session")
def raws(reg):
    return loader.load_all(DEFAULT, reg, None)


@pytest.fixture(scope="session")
def ground_truth():
    return json.loads((DATA / "tests_only" / "ground_truth.json").read_text())["series"]


@pytest.fixture(scope="session")
def golden():
    return json.loads((DATA / "tests_only" / "golden_cases.json").read_text())


@pytest.fixture(scope="session")
def manifest():
    return json.loads((DATA / "planted" / "planted_manifest.json").read_text())


AS_OF = pd.Timestamp("2026-10-15")


def pytest_configure(config):
    config.addinivalue_line("markers", "real_dotenv: test reads a .env file on purpose (the guard below is skipped)")


@pytest.fixture(autouse=True)
def _never_use_the_real_env_file(request, monkeypatch):
    """Tests must never pick up the project's real .env: no real API key (paid calls) and no FISHMARKET_LIVE=1 (network)."""
    if request.node.get_closest_marker("real_dotenv"):
        return
    from fishmarket import live, llm
    monkeypatch.setattr(llm, "_dotenv_value", lambda name: "")
    monkeypatch.setattr(live, "_dotenv", lambda name: "")
    monkeypatch.delenv("FISHMARKET_LIVE", raising=False)
    monkeypatch.setenv("FISHMARKET_LOG_MISSES", "0")             # tests never write to the real unanswered-question log
