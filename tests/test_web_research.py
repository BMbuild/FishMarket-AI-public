"""Web research: researcher-only permission, trusted sites first, max 3 searches, quotes only, off by default."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from fishmarket import permissions
from fishmarket.agents import researcher
from fishmarket.agents.agent1 import PLAN_TOOL
from fishmarket.agents.agent2 import ANALYSIS_TOOL
from fishmarket.llm import LLM, RunCtx
from fishmarket.qa import answer
from fishmarket.qa.context import Context

Q = "How many seafood processing plants operate in Ohio?"
HAIKU = "claude-haiku-5-5"


def cite(url, quote, title="Page"):
    return {"type": "web_search_result_location", "url": url, "title": title, "cited_text": quote, "encrypted_index": "x"}


def reply(citations, searches=1, prose="Here is what I found. You should buy now!"):
    blocks = [{"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "q"}} for _ in range(searches)]
    blocks += [{"type": "web_search_tool_result", "tool_use_id": "s1", "content": []},
               {"type": "text", "text": prose, "citations": citations}]
    return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=4000, output_tokens=200,
                                                                    server_tool_use=SimpleNamespace(web_search_requests=searches)))


class WebStub:
    """Fake Anthropic client: returns scripted web-search replies in order and records each request."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        return self.replies.pop(0)


@pytest.fixture(autouse=True)
def no_miss_log(monkeypatch):
    monkeypatch.setenv("FISHMARKET_LOG_MISSES", "0")


@pytest.fixture(scope="module")
def ctx():
    return Context.load(Path("/nonexistent-lake"), live=False)


TRUSTED = [cite("https://www.fisheries.noaa.gov/report", "Ohio had 12 seafood processing plants in the latest NOAA survey of processors.")]
OPEN = [cite("https://www.example-news.com/story", "An industry group counted 14 seafood processing plants in Ohio last year.")]


# ---- permission boundaries -------------------------------------------------------------------------
def test_only_the_researcher_may_search(cfg):
    llm = LLM(cfg, mode="live", client=WebStub([]))
    for agent in ("agent1", "agent2", "summary", "nobody"):
        with pytest.raises(permissions.PermissionDenied):
            llm.search_call(agent, "s", "u", HAIKU, 500, RunCtx(), 1, allowed_domains=["noaa.gov"])


def test_agents_may_only_use_their_own_tools(cfg):
    llm = LLM(cfg, mode="live", client=WebStub([]))
    with pytest.raises(permissions.PermissionDenied):
        llm.call("agent1", "s", "u", ANALYSIS_TOOL, HAIKU, 500, RunCtx())        # planner using the analyst's tool
    with pytest.raises(permissions.PermissionDenied):
        llm.call("researcher", "s", "u", PLAN_TOOL, HAIKU, 500, RunCtx())        # researcher has no structured tools
    with pytest.raises(permissions.PermissionDenied):
        llm.call("agent1", "s", "u", PLAN_TOOL, HAIKU, 50_000, RunCtx())         # over its output-token ceiling


def test_search_allowance_is_per_run_and_capped_at_three(cfg):
    stub = WebStub([reply([], searches=2), reply([], searches=1)])
    llm, run = LLM(cfg, mode="live", client=stub), RunCtx()
    llm.search_call("researcher", "s", "u1", HAIKU, 500, run, 2, allowed_domains=["noaa.gov"])
    llm.search_call("researcher", "s", "u2", HAIKU, 500, run, 1, blocked_domains=["reddit.com"])
    with pytest.raises(permissions.PermissionDenied):
        llm.search_call("researcher", "s", "u3", HAIKU, 500, run, 1, blocked_domains=["reddit.com"])
    assert len(stub.requests) == 2


def test_open_web_search_must_carry_the_blocked_list(cfg):
    llm = LLM(cfg, mode="live", client=WebStub([]))
    with pytest.raises(permissions.PermissionDenied):
        llm.search_call("researcher", "s", "u", HAIKU, 500, RunCtx(), 1)


# ---- researcher behaviour --------------------------------------------------------------------------
def test_trusted_sites_first_and_no_open_web_when_they_answer(cfg):
    stub = WebStub([reply(TRUSTED, searches=1)])
    out = researcher.research(Q, LLM(cfg, mode="live", client=stub), cfg)
    assert len(stub.requests) == 1
    tool = stub.requests[0]["tools"][0]
    assert tool["name"] == "web_search" and "noaa.gov" in tool["allowed_domains"] and tool["max_uses"] == 2
    assert [f["origin"] for f in out["facts"]] == ["WEB_TRUSTED"] and out["searches"] == 1


def test_open_web_only_when_trusted_sites_have_nothing(cfg):
    stub = WebStub([reply([], searches=2), reply(OPEN, searches=1)])
    out = researcher.research(Q, LLM(cfg, mode="live", client=stub), cfg)
    second = stub.requests[1]["tools"][0]
    assert "blocked_domains" in second and "reddit.com" in second["blocked_domains"] and second["max_uses"] == 1
    assert out["searches"] == 3 and [f["origin"] for f in out["facts"]] == ["WEB_OPEN"]


def test_only_quoted_text_survives_and_bad_citations_are_dropped(cfg):
    cites = TRUSTED + [cite("http://www.noaa.gov/x", "Plain http pages are never used as evidence here."),
                       cite("https://www.reddit.com/r/x", "A post says there are 99 plants in Ohio, trust me."),
                       cite("https://evil.example.com/a", "This open-web page sneaked into the trusted pass."),
                       cite("https://www.noaa.gov/y", "short")]
    out = researcher.research(Q, LLM(cfg, mode="live", client=WebStub([reply(cites)])), cfg)
    assert [f["url"] for f in out["facts"]] == ["https://www.fisheries.noaa.gov/report"]
    assert all("buy" not in f["text"].lower() for f in out["facts"])       # the model's own prose is discarded


def test_contact_details_never_reach_the_web(cfg):
    stub = WebStub([reply(TRUSTED)])
    researcher.research("Email me at bob@boat.com or call 207-555-0199: how many plants in Ohio?", LLM(cfg, mode="live", client=stub), cfg)
    sent = stub.requests[0]["messages"][0]["content"]
    assert "bob@boat.com" not in sent and "555" not in sent


def test_quotes_are_cleaned_of_markdown_and_html():
    facts, _ = researcher.facts_from_blocks([{"type": "text", "citations": [
        cite("https://www.noaa.gov/a", "Landings rose <script>x</script> see [link](javascript:alert) in `code` form today.")]}],
        "trusted", ["noaa.gov"], [])
    assert not any(ch in facts[0]["text"] for ch in "<>[]`")


def test_search_answers_are_cached(cfg):
    stub = WebStub([reply(TRUSTED)])
    llm = LLM(cfg, mode="auto", client=stub)
    a = researcher.research(Q, llm, cfg)
    b = researcher.research(Q, llm, cfg)
    assert len(stub.requests) == 1 and a["facts"] == b["facts"]


# ---- QA engine ---------------------------------------------------------------------------------------
def test_web_is_off_by_default(cfg, ctx):
    stub = WebStub([reply(TRUSTED)])
    r = answer.ask(Q, ctx, llm=LLM(cfg, mode="live", client=stub), cfg=cfg, summarise=False)
    assert r["verdict"] == "cannot"
    assert not any(t.get("name") == "web_search" for req in stub.requests for t in req.get("tools", []))


def test_web_answer_when_local_data_cannot(cfg, ctx):
    stub = WebStub([reply(TRUSTED)])
    llm = LLM(cfg, mode="live", client=stub)
    llm.call = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no planner or summary call expected"))
    import fishmarket.qa.router as router
    orig = router.refine_with_llm
    router.refine_with_llm = lambda plan, *a, **k: (plan, 0.0)
    try:
        r = answer.ask(Q, ctx, llm=llm, cfg=cfg, summarise=False, web=True)
    finally:
        router.refine_with_llm = orig
    assert r["entry_id"] == "web_research" and r["verdict"] == "partly" and r["confidence"] == "Medium"
    assert r["origins"] == ["WEB (trusted source, quoted)"]
    assert "https://www.fisheries.noaa.gov/report" in r["answer_md"] and "12" in r["answer_md"]


def test_no_web_for_answerable_or_foreign_questions(cfg, ctx):
    stub = WebStub([reply(TRUSTED)])
    llm = LLM(cfg, mode="live", client=stub)
    import fishmarket.qa.router as router
    orig = router.refine_with_llm
    router.refine_with_llm = lambda plan, *a, **k: (plan, 0.0)
    try:
        answer.ask("What is the price of salmon in Norway?", ctx, llm=llm, cfg=cfg, summarise=False, web=True)
        answer.ask("What does the FDA say about histamine in mahi-mahi?", ctx, llm=llm, cfg=cfg, summarise=False, web=True)
    finally:
        router.refine_with_llm = orig
    assert not stub.requests


def test_writer_numbers_must_come_from_the_quotes(cfg, ctx):
    from fishmarket import real_summary
    claims = [{"id": "W1", "text": TRUSTED[0]["cited_text"]}, {"id": "CAV", "text": answer.WEB_CAVEAT}]
    ok, _ = real_summary.grounded("A NOAA page says Ohio had 12 seafood processing plants.", claims)
    bad, why = real_summary.grounded("A NOAA page says Ohio had 40 seafood processing plants.", claims)
    assert ok and not bad and "40" in why


# ---- scenario text box ---------------------------------------------------------------------------------
def test_note_question_is_found():
    from fishmarket import scenario_context as sc
    assert sc.note_question("I run two boats. How many seafood processing plants operate in Ohio? Thanks.") == \
        "How many seafood processing plants operate in Ohio?"
    assert sc.note_question("No questions here.") == ""


def test_scenario_question_uses_web_only_when_ticked(cfg):
    from fishmarket import scenario_context as sc
    stub = WebStub([reply(TRUSTED)])
    llm = LLM(cfg, mode="live", client=stub)
    off = sc.answer_question(Q, ("Cod",), "Northeast", llm=llm, web=False, cfg=cfg)
    assert off["verdict"] == "cannot" and not stub.requests
    on = sc.answer_question(Q, ("Cod",), "Northeast", llm=llm, web=True, cfg=cfg)
    assert on["web_searches"] == 1 and "WEB (trusted source, quoted)" in on["origins"]
    assert on["agent_text"] and not any(ch.isdigit() for ch in on["agent_text"])       # agents get words only
