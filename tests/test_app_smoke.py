"""Smoke test for app/streamlit_app.py with a recording stand-in for the streamlit module.
It proves the script's logic runs (presets, species filtering, conflict handling, live run, result screen).
It cannot prove how the page looks in a browser."""
import runpy
import sys
import types
from unittest.mock import MagicMock

import pytest

from fishmarket.config import DEFAULT, ROOT


class SS(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


class Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __getattr__(self, name): return lambda *a, **k: None


class FakeSt(types.ModuleType):
    def __init__(self, presses=()):
        super().__init__("streamlit")
        self.session_state, self.presses, self.calls = SS(), set(presses), []
        self.sidebar = self

    def cache_data(self, f=None, **kw):
        return f if f else (lambda g: g)

    cache_resource = cache_data

    def selectbox(self, label, options, key=None, format_func=None, **kw):
        options = list(options)
        v = self.session_state.get(key)
        if v not in options:
            v = options[0]
        self.session_state[key] = v
        return v

    radio = selectbox

    def multiselect(self, label, options, key=None, **kw):
        options = list(options)
        v = [x for x in self.session_state.get(key, []) if x in options]
        self.session_state[key] = v
        return v

    def text_area(self, label, key=None, **kw):
        return self.session_state.get(key, "")

    text_input = text_area

    def number_input(self, label, key=None, **kw):
        return self.session_state.get(key)

    def checkbox(self, label, key=None, **kw):
        self.calls.append(("checkbox", key, kw.get("disabled")))
        return self.session_state.get(key, False)

    def button(self, label, key=None, on_click=None, args=(), **kw):
        return label in self.presses

    def columns(self, n, **kw):
        return [self for _ in range(n if isinstance(n, int) else len(n))]

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def expander(self, *a, **k): return Ctx()
    def empty(self): return Ctx()
    def container(self, **k): return Ctx()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        def rec(*a, **k):
            self.calls.append((name, a))
            return Ctx()
        return rec


BASE = {"region": "Gulf", "operation": "wild_catch", "species": ["Gulf shrimp"], "storage": "none",
        "question_type": "sell_or_hold", "free_text": "", "experience": "", "goal": "", "constraints": [],
        "customer_segment": "mainstream", "volume": 40000.0}


def run_app(presses=(), state=None, page="Scenario demo (fictional)"):
    fake = FakeSt(presses)
    fake.session_state["page"] = page
    if state is not None:
        fake.session_state.update({**BASE, **state})
    sys.modules["streamlit"] = fake
    try:
        g = runpy.run_path(str(ROOT / "app" / "streamlit_app.py"))
    finally:
        sys.modules.pop("streamlit", None)
        sys.modules.pop("extra_pages", None)   # it binds the stand-in at import time
    return fake, g


@pytest.fixture(autouse=True)
def cleanup_runs():
    before = set((ROOT / "runs").glob("*.json"))
    yield
    for p in set((ROOT / "runs").glob("*.json")) - before:
        p.unlink()


def test_app_applies_first_preset_when_state_is_empty():
    fake, _ = run_app()
    assert fake.session_state["region"] == "Gulf" and fake.session_state["pp_PP-STALE"] is False


def test_app_renders_without_running():
    fake, _ = run_app(state={"mode": "fake", "region": "Gulf", "species": ["Gulf shrimp"]})
    assert fake.session_state["region"] == "Gulf" and fake.session_state["species"] == ["Gulf shrimp"]
    assert any(c[0] == "warning" and "Fictional data" in c[1][0] for c in fake.calls)   # persistent banner
    assert fake.session_state["result"] is None


def test_run_with_scripted_model_produces_a_result_screen():
    fake, _ = run_app({"Run analysis"}, {"mode": "fake"})
    res = fake.session_state["result"]
    assert res["status"] == "ok" and res["report"]["direction"] == "hold"
    names = [c[0] for c in fake.calls]
    assert "line_chart" in names and "dataframe" in names and "success" in names


def test_planted_toggles_flow_into_the_run():
    state = {"mode": "fake", "pp_PP-CONFLICT": True, "pp_PP-STALE": True}
    fake, _ = run_app({"Run analysis"}, state)
    r = fake.session_state["result"]
    assert r["trust"]["rating"] == "low" and {"source_disagreement", "stale_data"} <= set(r["flags"])


def test_conflicting_planted_cases_cannot_both_be_on():
    fake, g = run_app(state={"mode": "fake", "pp_PP-UNIT": True, "pp_PP-DUPMISS": True})
    boxes = {c[1]: c[2] for c in fake.calls if c[0] == "checkbox"}
    assert boxes["pp_PP-UNIT"] is False and boxes["pp_PP-DUPMISS"] is True       # second one disabled
    fake.session_state.update(pp_STALE=False)
    assert g["active_cases"]() == ["PP-UNIT"]


def test_species_list_follows_region():
    fake, _ = run_app(state={"mode": "fake", "region": "Pacific Northwest", "species": ["Gulf shrimp"]})
    assert fake.session_state["species"][0] in {"Wild salmon", "Cod", "Dungeness crab", "Sockeye salmon", "Pacific halibut",
                                                "Alaska pollock", "Blue mussels"}


def test_bad_profile_shows_an_error_not_a_crash():
    fake, _ = run_app({"Run analysis"}, {"mode": "fake", "volume": 0.0})
    assert fake.session_state["result"] is None
    assert any(c[0] == "error" and "greater than 0" in c[1][0] for c in fake.calls)


def test_intro_page_explains_the_site():
    fake, _ = run_app(page="Introduction")
    text = " ".join(str(c[1][0]) for c in fake.calls if c[0] == "markdown")
    assert "What it does" in text and "What it will not do" in text and "<svg" in text


def test_data_sources_page_flags_placeholder_links():
    fake, _ = run_app(page="Data sources")
    text = " ".join(str(c[1][0]) for c in fake.calls if c[0] == "markdown")
    assert "Needs a real dataset link" in text


@pytest.mark.skipif(not (ROOT / "noaa_landings_full.csv").exists(), reason="NOAA csv not present")
def test_real_data_page_renders():
    fake, _ = run_app(page="Real NOAA data")
    assert any(c[0] == "success" for c in fake.calls)
    assert any(c[0] == "line_chart" for c in fake.calls)


@pytest.mark.skipif(not (ROOT / "noaa_landings_full.csv").exists(), reason="NOAA csv not present")
def test_real_page_shows_states_summary_and_browse():
    fake, _ = run_app(page="Real NOAA data", state={"real_view": "Species report"})
    assert sum(1 for c in fake.calls if c[0] == "dataframe") >= 1
    assert any(c[0] == "markdown" and "highly concentrated" in str(c[1][0]) for c in fake.calls) or any(c[0] == "write" for c in fake.calls)
    fake, _ = run_app(page="Real NOAA data", state={"real_view": "Browse the market"})
    assert sum(1 for c in fake.calls if c[0] == "dataframe") >= 3


def test_any_species_own_question_and_free_goals_flow_into_the_run():
    state = {"mode": "fake", "operation": "pot_trap_fisher", "region": "Alaska", "species": ["Snow crab"],
             "species_typed": "Golden king crab", "question_type": "own_question", "own_question": "When should I sell my crab?",
             "goal_typed": "pay off the boat", "constraints_typed": "one buyer only; crew leaves in March", "storage": "frozen",
             "species_region": "Alaska"}
    fake, _ = run_app({"Run analysis"}, state)
    r = fake.session_state["result"]
    assert r["status"] == "ok", fake.calls[-5:]
    assert r["report"]["question_type"] == "sell_or_hold"            # two species: a ranking question is not run
    sit = r["report"]["your_situation"]
    assert sit["goal"] == "pay off the boat" and "crew leaves in March" in sit["constraints"]
    charts = [c for c in fake.calls if c[0] in ("line_chart", "bar_chart")]
    assert charts


def test_pot_trap_alaska_lists_crabs_first():
    fake, _ = run_app(state={"mode": "fake", "operation": "pot_trap_fisher", "region": "Alaska", "species": []})
    assert fake.session_state["species"] == ["King crab"]          # the best fit is the default pick
