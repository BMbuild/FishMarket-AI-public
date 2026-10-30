"""Answerability, confidence, composition and the ask() entry point."""
from __future__ import annotations

import csv
import dataclasses
import re
from pathlib import Path

from ..config import DEFAULT
from ..contracts import ensure_confirmable, FlaggedRecordError
from .. import real_summary, wiki
from . import catalogue, misses, router, tools
from .context import Context
from .origin import PILL, SYNTH_SENTENCE, check_claims

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "data_real" / "dataset_registry.csv"
ADVICE_LINE = "This tool reports history and patterns. It does not give financial advice or forecasts."
FORECAST_LINE = "I can't forecast prices. Here is what the data shows about the past."
INJECTION_LINE = "Part of your message looked like instructions to an AI and was ignored."
LEVELS = {"High": 3, "Medium": 2, "Low": 1}


def _registry() -> dict:
    with open(REGISTRY, newline="") as f:
        return {r["dataset_id"]: r for r in csv.DictReader(f)}


def citations(ids: list[str], ctx: Context) -> list[str]:
    reg, out = _registry(), []
    for d in dict.fromkeys(ids):
        if d.startswith("WIKI:"):
            w = wiki.load().get(d[5:])
            if w:
                out.append(f"Mini-wiki: {w.title}. Source: {' '.join(w.sources)} (read {w.retrieved})")
            continue
        r = reg.get(d)
        if not r:
            continue
        line = f"{r['name']} ({r['owner']}). {r['url']}"
        if d == "GBIF-OCC":
            m = ctx.gold.manifest
            if m.get("is_test_fixture"):
                line = "TEST FIXTURE: synthetic GBIF-shaped test data, not real GBIF records. No citation applies."
            elif m.get("source_kind") == "api_sample":
                line = (f"GBIF.org occurrence search API (https://api.gbif.org/v1/occurrence/search), a sample of up to a few hundred "
                        f"records per species, lake built {m.get('built_at', '')[:10]}. Not a complete GBIF download, so no download DOI applies.")
            elif m.get("doi"):
                line = f"GBIF.org ({m.get('built_at', '')[:10]}) GBIF Occurrence Download https://doi.org/{m['doi']}"
            else:
                line = "GBIF occurrence download. The download DOI is missing from the manifest, so this citation is incomplete (citation_incomplete)."
        out.append(line)
    return out


def confidence(res: tools.ToolResult, plan: router.QueryPlan, ctx: Context) -> tuple[str, list[str]]:
    level, why = "High", []

    def cap(to, reason):
        nonlocal level
        if LEVELS[to] < LEVELS[level]:
            level = to
        why.append(reason)
    origins = {c.origin for c in res.claims}
    if origins & {"SYNTHETIC", "TEST_FIXTURE"}:
        cap("Low", "Synthetic or test data contributes to this answer, which caps confidence at Low.")
    if res.handoff and res.handoff.status == "WARNING":
        cap("Medium", f"Validation gate warning: {res.handoff.flag_reason}")
    ds = {c.dataset_id for c in res.claims}
    if any(d.startswith("WIKI:") for d in ds):
        cap("Medium", "This comes from short notes on public NOAA and FDA pages, which can change; the source link is the authority.")
    if ds & {"OBIS-OCC", "CENSUS-TRADE", "OECD-AQUA", "FISHWATCH"}:
        cap("Medium", "This comes from a live public API call; counts and values depend on what the source holds today.")
    if origins & {"REAL_GBIF"}:
        cap("Medium", "GBIF counts depend on where and when people looked.")
    if res.match_type == "genus_level" or res.partial:
        cap("Medium", "The species is linked at genus level only." if res.match_type == "genus_level" else res.partial)
    if res.entry_id in ("landings_vs_sightings", "recent_sightings_in_region") or (res.entry_id == "seasonal_presence" and plan.region):
        cap("Medium", "Regions are approximate boxes, not official boundaries.")
    a = res.data.get("analysis")
    if a and a.get("years_of_data", 99) < 10:
        cap("Medium", "Short history (under 10 years).")
    if plan.assumed:
        why.append(plan.assumed[0])
    if not why:
        why.append("Real NOAA data passed the validation gate with no warnings.")
    return level, why


def _template(claims: list[dict]) -> str:
    return real_summary.template(claims)


def _cannot(plan, verdict, reason, extra=None) -> dict:
    return {"verdict": verdict, "entry_id": plan.entry_id, "answer_md": reason, "claims": [], "evidence": [], "confidence": None,
            "confidence_reasons": [], "caveats": [], "origins": [], "citations": [], "flags": _flags(plan), "plan": plan,
            "cost_usd": 0.0, "source": "none", "source_reason": "", **(extra or {})}


def _flags(plan) -> list[str]:
    f = []
    if plan.injection:
        f.append("untrusted_text_ignored")
    if plan.forecast:
        f.append("forecast_request")
    if plan.advice:
        f.append("advice_request")
    return f


FARM = re.compile(r"\b(farm|farms|farmed|farmer|farmers|farming|aquaculture|feed|pens?|hatchery|net pen)\b", re.I)


def ask(question: str, ctx: Context, llm=None, species: str | None = None, region: str | None = None, real_only: bool | None = None,
        mix: str = "dev", cfg=DEFAULT, summarise: bool = True, web: bool = False, web_context: str = "") -> dict:
    """Answers the question and logs it locally if it could not be answered (see qa/misses.py).
    With web=True (off by default) and an AI-mode llm, a question the local data cannot answer goes to the web researcher."""
    r = _ask(question, ctx, llm, species, region, real_only, mix, cfg, summarise)
    misses.record(question, r)
    if web and web_allowed(r) and llm is not None and hasattr(llm, "search_call"):
        w = web_answer(question, llm, cfg, mix, summarise, local=r, context=web_context)
        if w is not None:
            return w
    return r


def web_allowed(r: dict) -> bool:
    """Only questions the local data could not answer, and never out-of-scope or instruction-like ones."""
    plan = r.get("plan")
    if r.get("verdict") != "cannot":
        return False
    if plan is not None and (plan.scope == "non_us" or plan.injection):
        return False
    return True


WEB_CAVEAT = ("These quotes come from web pages, not from the checked NOAA, GBIF or OECD data. Python checked that every number "
              "is in a quote, but not that the page is right: open the links before relying on them.")


def web_answer(question: str, llm, cfg=DEFAULT, mix: str = "dev", summarise: bool = True, local: dict | None = None,
               context: str = "", run_ctx=None) -> dict | None:
    from ..agents import researcher
    res = researcher.research(question, llm, cfg, mix, context=context, run_ctx=run_ctx)
    local_md = (local or {}).get("answer_md", "")
    head = f"Local data couldn't answer this, so the researcher searched the web ({res['searches']} search{'es' if res['searches'] != 1 else ''})."
    if not res["facts"]:
        why = res["error"] or "No usable quotes were found on trusted sites or the open web."
        if local is None:
            return None
        out = dict(local)
        out["answer_md"] = local_md + f"\n\n*Web research was tried: {why}*"
        out["cost_usd"] = local.get("cost_usd", 0.0) + res["cost_usd"]
        out["web"] = {"searches": res["searches"], "passes": res["passes"], "error": res["error"], "facts": []}
        return out
    facts = res["facts"]
    claims = [{"id": f["id"], "text": f["text"]} for f in facts]
    cav = {"id": "CAV", "text": WEB_CAVEAT}
    text, source, reason, cost, unv = "", "template", "", res["cost_usd"], None
    if summarise:
        s = real_summary.summarise(claims + [cav], llm, ctx=run_ctx, cfg=cfg, mix=mix, system=real_summary.WEB_SYSTEM)
        cost += s.get("cost_usd", 0.0)
        if s["source"] == "ai":
            text, source = s["markdown"], "ai"
        else:
            reason, unv = s.get("reason", ""), s.get("unverified_markdown")
    quotes = "\n".join(f"- {f['id']}: \u201c{f['text']}\u201d ([{f['title']}]({f['url']}))" for f in facts)
    md = head + ("\n\n" + text if text else "") + "\n\n**What the pages say (quoted):**\n\n" + quotes + f"\n\n*{WEB_CAVEAT}*"
    trusted = all(f["origin"] == "WEB_TRUSTED" for f in facts)
    ev = [{"claim": f["id"], "text": f["text"], "dataset": f["host"], "query": "web_search", "rows": 0, "origin": PILL[f["origin"]], "url": f["url"]} for f in facts]
    return {"verdict": "partly", "entry_id": "web_research", "answer_md": md, "claims": claims, "evidence": ev,
            "confidence": "Medium" if trusted else "Low",
            "confidence_reasons": ["All quotes are from trusted official sites." if trusted else "Some quotes are from the open web.",
                                   "Web pages are not checked against the local data."],
            "caveats": [WEB_CAVEAT], "origins": sorted({PILL[f["origin"]] for f in facts}),
            "citations": list(dict.fromkeys(f"{f['title']}: {f['url']}" for f in facts)), "flags": ["web"],
            "plan": (local or {}).get("plan"), "cost_usd": (local or {}).get("cost_usd", 0.0) + cost, "source": source, "source_reason": reason,
            "unverified": ({"markdown": unv, "problem": reason.split(": ", 1)[-1]} if unv else None), "data": {},
            "web": {"searches": res["searches"], "passes": res["passes"], "error": res["error"], "facts": facts}}


def _ask(question: str, ctx: Context, llm=None, species: str | None = None, region: str | None = None, real_only: bool | None = None,
         mix: str = "dev", cfg=DEFAULT, summarise: bool = True) -> dict:
    """Answers one question, or each part of a compound question ("..., and what ...?") as its own checked answer."""
    parts = router.split_question(question)
    first = router.plan(question, ctx, None, region)
    if len(parts) > 1 and not species and not first.injection and all(len(p) <= 160 for p in parts):
        # (never split text that looks like instructions: the parts are echoed as headings)
        sp = first.species[0] if first.species else None
        subs = [ask_one(p, ctx, llm, species or sp if not router.plan(p, ctx).species else None, region, real_only, mix, cfg, summarise) for p in parts]
        if FARM.search(question) and any(r["entry_id"] == "aquaculture_production" and r["verdict"] == "answered" for r in subs):
            # in a farming question, "what is it worth?" is answered by OECD's farm value above, not by wild-catch dock prices
            keep = [(p, r) for p, r in zip(parts, subs) if not (r["entry_id"] in ("price_history", "price_vs_inflation") and not router.plan(p, ctx).species)]
            if len(keep) < len(parts):
                parts, subs = [p for p, _ in keep], [r for _, r in keep]
                if len(subs) == 1:
                    subs[0]["answer_md"] += "\n\n*The value per pound above is OECD's farm value; NOAA dock prices cover wild catch only.*"
                    return subs[0]
        if sum(1 for r in subs if r["entry_id"]) >= 2:
            return combine(question, parts, subs)
    if not species and len(first.species) >= 2 and first.entry_id and first.entry_id not in MULTI_SPECIES_ENTRIES and not first.injection:
        # a single-species question type asked about several species: answer each one separately, under its own heading
        subs = [ask_one(_only(question, sp, first.species, ctx), ctx, llm, sp, region, real_only, mix, cfg, summarise) for sp in first.species]
        return combine(question, list(first.species), subs, heading=lambda label: label)
    return ask_one(question, ctx, llm, species, region, real_only, mix, cfg, summarise)


def _only(question: str, keep: str, all_species: list[str], ctx=None) -> str:
    """The question with the other species' names removed, so each per-species answer only sees its own species."""
    q = router.expand_shared_heads(question, ctx) if ctx is not None else question
    for other in all_species:
        if other != keep:
            q = re.sub(r"(?<![a-z])" + re.escape(other) + r"(?:e?s)?(?![a-z])", " ", q, flags=re.I)
    return re.sub(r"\s+", " ", q)


MULTI_SPECIES_ENTRIES = {"compare_species", "biggest_movers", "data_quality"}
RANK = {"answered": 0, "partly": 1, "clarify": 2, "cannot": 3}
LEVELS_ORDER = ["Low", "Medium", "High"]


def combine(question: str, parts: list[str], subs: list[dict], heading=None) -> dict:
    """Each part keeps its own answer, origins and caveats; nothing is merged across parts, so origin rules still hold."""
    head = heading or (lambda p: p)
    md = "\n\n".join(f"**{i}. {head(p)}**\n\n{r['answer_md']}" for i, (p, r) in enumerate(zip(parts, subs), 1))
    confs = [r["confidence"] for r in subs if r.get("confidence")]
    worst = min(confs, key=LEVELS_ORDER.index) if confs else None
    verdicts = [r["verdict"] for r in subs]
    verdict = "answered" if all(v == "answered" for v in verdicts) else "partly" if any(v in ("answered", "partly") for v in verdicts) else max(verdicts, key=RANK.get)
    uniq = lambda xs: list(dict.fromkeys(xs))
    return {"verdict": verdict, "entry_id": "+".join(r["entry_id"] or "none" for r in subs), "answer_md": md,
            "claims": [c for r in subs for c in r.get("claims", [])], "evidence": [e for r in subs for e in r.get("evidence", [])],
            "confidence": worst, "confidence_reasons": uniq([x for r in subs for x in r.get("confidence_reasons", [])]),
            "caveats": uniq([x for r in subs for x in r.get("caveats", [])]), "origins": sorted({o for r in subs for o in r.get("origins", [])}),
            "citations": uniq([x for r in subs for x in r.get("citations", [])]), "flags": uniq([x for r in subs for x in r.get("flags", [])]),
            "plan": subs[0].get("plan"), "cost_usd": sum(r.get("cost_usd", 0.0) for r in subs),
            "source": "+".join(r.get("source", "") for r in subs), "source_reason": " | ".join(r.get("source_reason", "") for r in subs if r.get("source_reason")),
            "unverified": next((r["unverified"] for r in subs if r.get("unverified")), None), "data": subs[0].get("data") or {}, "parts": subs}


def ask_one(question: str, ctx: Context, llm=None, species: str | None = None, region: str | None = None, real_only: bool | None = None,
            mix: str = "dev", cfg=DEFAULT, summarise: bool = True) -> dict:
    real_only = ctx.real_only if real_only is None else real_only
    if real_only and not ctx.real_only:
        ctx = dataclasses.replace(ctx, real_only=True)          # tools see the mode too, so none of them can offer a generated stand-in
    plan = router.plan(question, ctx, species, region)
    cost = 0.0
    if llm is not None:
        plan, c = router.refine_with_llm(plan, llm, cfg, mix)
        cost += c
    cat = catalogue.load()
    if plan.scope == "non_us":
        return _cannot(plan, "cannot", router.US_ONLY)
    if plan.entry_id is None:
        ex = [cat[k]["examples"][0].replace("{species}", "American lobster").replace("{species2}", "haddock").replace("{region}", "the Gulf") for k in list(cat)[:4]]
        return _cannot(plan, "cannot", "I can't answer that with the data here: it doesn't match any question type I can check against NOAA or GBIF. "
                                      "Questions I can answer look like: " + " | ".join(ex))
    e = cat[plan.entry_id]
    if plan.clarify:
        return _cannot(plan, "clarify", plan.clarify)
    if e["kind"] == "needs_fill_data" and (real_only or not ctx.allow_synthetic):
        return _cannot(plan, "cannot", f"This needs data that NOAA and GBIF don't contain ({e['category'].lower()}), and real-only mode forbids generated or fictional stand-ins. "
                                      f"{e['caveats']}")
    if e["data"] in ("gbif", "both") and not ctx.gold.available:
        return _cannot(plan, "cannot", "The GBIF data hasn't been built yet. Run `python -m fishmarket.lake build <download>` (or `--sample` for the test fixture), then ask again.")
    if e["tool"] == "none":   # kept for entries with no tool
        return _cannot(plan, "cannot", f"NOAA and GBIF have no {e['category'].lower()} data. The Scenario demo has fictional cost, quality and storage data you can explore, "
                                      "but it can't tell you about your real business.")
    if e["tool"] in ("wiki_lookup", "seafood_trade", "aquaculture_production", "farming_profile", "compare_species"):
        res = tools.TOOLS[e["tool"]](ctx, plan.species, plan.region, plan.years, question=question)
    else:
        res = tools.TOOLS[e["tool"]](ctx, plan.species, plan.region, plan.years)
    if res.refusal:
        return _cannot(plan, "cannot", res.refusal, {"caveats": res.caveats})
    try:
        if res.handoff:
            ensure_confirmable([res.handoff])
    except FlaggedRecordError as ex:
        return _cannot(plan, "cannot", f"The validation gate stopped this answer: {ex}")
    check_claims(res.claims)
    level, why = confidence(res, plan, ctx)
    claims = [{"id": c.id, "text": c.text} for c in res.claims]
    caveats = list(dict.fromkeys(res.caveats + ([e["caveats"]] if e.get("caveats") else [])))
    if plan.state and plan.region:
        caveats.append(f"{plan.state.title()} is in the {plan.region} region; this answer is for the region.")
    if any(c.origin in ("SYNTHETIC",) for c in res.claims) and not any(SYNTH_SENTENCE in c.text for c in res.claims if c.origin == "SYNTHETIC"):
        caveats.append(SYNTH_SENTENCE)
    if FARM.search(question) and plan.entry_id not in ("wiki_lookup", "aquaculture_production", "farming_profile"):
        caveats.append("NOAA landings cover wild-caught fish only, so they do not describe farmed fish prices, feed or farm costs.")
    cav = {"id": "CAV", "text": caveats[0] if caveats else "These figures describe the past."}
    base = real_summary.template(claims + [cav])
    text, source, src_reason, unverified_md = base, "template", "", None
    if llm is not None and summarise and plan.entry_id not in ("wiki_lookup", "farming_profile") and getattr(llm, "mode", "") != "fake":   # wiki text is quoted as written
        out = real_summary.summarise(claims + [cav], llm, cfg=cfg, mix=mix)
        text, source, cost = out["markdown"], out["source"], cost + out.get("cost_usd", 0.0)
        src_reason = out.get("reason", "")
        unverified_md = out.get("unverified_markdown")
    notes = []
    if plan.forecast:
        notes.append(FORECAST_LINE)
    if plan.advice:
        notes.append(ADVICE_LINE)
    if plan.injection:
        notes.append(INJECTION_LINE)
    notes += plan.assumed
    if res.partial:
        notes.append(res.partial)
    verdict = "partly" if (plan.forecast or plan.advice or res.partial) else "answered"
    ids = [c.dataset_id for c in res.claims]
    ev = [{"claim": c.id, "text": c.text, "dataset": c.dataset_id, "query": c.query_id, "rows": c.rows_used, "origin": PILL.get(c.origin, c.origin)} for c in res.claims]
    return {"verdict": verdict, "entry_id": plan.entry_id, "answer_md": ("\n\n".join(notes) + "\n\n" if notes else "") + text, "claims": claims, "evidence": ev,
            "confidence": level, "confidence_reasons": why, "caveats": caveats, "origins": sorted({PILL.get(c.origin, c.origin) for c in res.claims}),
            "citations": citations(ids, ctx), "flags": _flags(plan), "plan": plan, "cost_usd": cost, "source": source, "source_reason": src_reason,
            "unverified": ({"markdown": unverified_md, "problem": src_reason.split(": ", 1)[-1]} if unverified_md else None), "data": res.data,
            "tool_result": res}
