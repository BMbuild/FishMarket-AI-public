"""The eight-step pipeline: three paid AI agents with Python in between."""
from __future__ import annotations

import json
from decimal import Decimal
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from . import unverified
from . import scenario_context
from . import report as report_mod
from .agents import agent1, agent2, summary as summary_agent
from .analytics import compute_stats
from . import note as note_mod
from . import scenario_species, situation
from .config import (DEFAULT, QUESTION_LABELS, QUESTION_TYPES, Config)
from .extras import Extras
from .grounding import expected_tags
from .questions import analyse_species, decide, merge
from .events import Tracer
from .gate import GateReport, run_gate
from .grounding import check_analysis
from .llm import LLM, LLMError, RunCtx
from .loader import Overrides, covers_series, load_all
from .registry import (load_catalog, load_operations, load_registry, load_segments, price_sources, regions,
                       species_for_region)
from .schemas import Profile, RequestBrief
from .templates import (caveats_for, check_summary, recommendation_sentence, template_analysis, template_summary,
                        timing_window)
from .trust import compute_trust

FALLBACK_SOURCE = "SRC-SMP-01"


class ProfileError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def build_brief(raw: dict, catalog: pd.DataFrame, cfg: Config = DEFAULT, ops: Optional[pd.DataFrame] = None,
                segments: Optional[pd.DataFrame] = None) -> RequestBrief:
    """Step 1: validate the profile. Collects every problem so the user can fix them in one go.
    Regions, operations, segments and species come from the data files, never from code."""
    ops = ops if ops is not None else load_operations(cfg)
    segments = segments if segments is not None else load_segments(cfg)
    p: list[str] = []
    region = raw.get("region")
    all_regions = regions(catalog)
    if region not in all_regions:
        p.append(f"region must be one of {all_regions}.")
    op_id = raw.get("operation_type") or raw.get("business_type")
    op = ops.loc[op_id] if op_id in ops.index else None
    if op is None:
        p.append(f"operation_type must be one of {list(ops.index)}.")
    if raw.get("customer_segment") not in segments.index:
        p.append(f"customer_segment must be one of {list(segments.index)}.")
    own_q = note_mod.sanitise(str(raw.get("own_question") or ""), 300)["text"]
    qtype = raw.get("question_type") or ("own_question" if own_q else None) or (op["default_question_type"] if op is not None else "sell_or_hold")
    matched = True
    if qtype == "own_question":
        # a typed question runs the nearest calculation the operation may ask; with no match, the default one runs
        if not own_q:
            p.append("Type your question, or pick one from the list.")
        allowed = list(op["allowed"]) if op is not None else list(QUESTION_TYPES)
        many = isinstance(raw.get("species"), list) and len(raw.get("species")) > 1
        if many:      # ranking calculations take one species; with several, the question is answered separately
            allowed = [q for q in allowed if q in ("sell_or_hold", "buy_now_or_wait")]
        hit = situation.match_question(own_q, allowed, cfg.DATA_DIR)
        matched = hit is not None
        qtype = hit or (op["default_question_type"] if op is not None else "sell_or_hold")
        if many and qtype not in ("sell_or_hold", "buy_now_or_wait"):
            qtype = "sell_or_hold" if "sell_or_hold" in allowed or op is None else allowed[0] if allowed else "sell_or_hold"
    if qtype not in QUESTION_TYPES:
        p.append(f"question_type must be one of {list(QUESTION_TYPES)}.")
    elif op is not None and qtype not in op["allowed"]:
        p.append(f"{op_id} can ask: {op['allowed']}. {qtype!r} is not one of them.")
    species = raw.get("species")
    if isinstance(species, str):
        species = [species]
    if isinstance(species, list):
        cleaned = [scenario_species.clean_name(s) for s in species]
        if any(not c for c in cleaned):
            p.append("Species names may use letters, numbers, spaces and simple punctuation only (up to 60 characters).")
        # match the catalogue's spelling when the user typed a known name in another case
        known = {k.lower(): k for k in catalog.index}
        species = [known.get(c.lower(), c) for c in cleaned if c]
    if not isinstance(species, list) or not 1 <= len(species) <= cfg.MAX_SPECIES:
        p.append(f"Choose between 1 and {cfg.MAX_SPECIES} species.")
    else:
        if len(set(species)) != len(species):
            p.append("Each species can be listed only once.")
        if len(species) > 1 and qtype not in ("sell_or_hold", "buy_now_or_wait"):
            p.append("More than one species is supported only for sell-or-hold and buy-now-or-wait questions.")
        # Any species is accepted in any region: pairs with no hand-made fictional series are generated
        # (scenario_species.augment), and a species unusual for the operation gets a caveat, not an error.
    try:
        vol = float(raw.get("volume_lb_per_month"))
        if not vol > 0:
            raise ValueError
    except (TypeError, ValueError):
        p.append("volume_lb_per_month must be a number greater than 0.")
        vol = 0.0
    storage = raw.get("storage") or "none"
    if storage not in ("none", "chilled", "frozen"):
        p.append("storage must be none, chilled or frozen.")
    as_of = raw.get("as_of") or cfg.AS_OF_DEFAULT
    try:
        date.fromisoformat(str(as_of))
    except ValueError:
        p.append("as_of must be a valid date like 2026-10-15.")
    if p:
        raise ProfileError(p)
    prof = Profile(region=region, business_type=op_id, species=list(species),
                   customer_segment=raw["customer_segment"], volume_lb_per_month=vol, as_of=str(as_of),
                   question_type=qtype, question=QUESTION_LABELS[qtype], storage=storage,
                   free_text=str(raw.get("free_text") or ""), experience=str(raw.get("experience") or "")[:40],
                   goal=(situation.clean_items([raw.get("goal") or ""])[0] or [""])[0],
                   constraints=situation.clean_items(list(raw.get("constraints") or []))[0],
                   own_question=own_q, question_matched=matched)
    return RequestBrief(profile=prof, species=species[0], region=region, series=f"{species[0]}|{region}",
                        question=prof.question, all_species=list(species))


def _worst(ratings: list[str]) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    return min(ratings, key=lambda r: order[r])


def run(profile: dict, overrides: Optional[Overrides] = None, on_event: Optional[Callable[[dict], None]] = None,
        llm=None, cfg: Config = DEFAULT, mix: str = "dev", run_id: Optional[str] = None, save: bool = True) -> dict:
    tr = Tracer(run_id, on_event)
    tr.pending()
    ctx = RunCtx(run_id=tr.run_id)
    llm = llm or LLM(cfg)
    models = cfg.MODEL_MIX[mix]
    notes: list[str] = []

    # ---- step 1 -------------------------------------------------------------
    ev = tr.begin("profile")
    catalog = load_catalog(cfg)
    ops = load_operations(cfg)
    try:
        brief = build_brief(profile, catalog, cfg, ops, load_segments(cfg))
    except ProfileError as e:
        tr.finish(ev, "failed", "The profile has problems: " + " ".join(e.problems), {"problems": e.problems})
        raise
    prof = brief.profile
    qtype = prof.question_type
    op_row = ops.loc[prof.business_type].to_dict()
    as_of = pd.Timestamp(prof.as_of)
    registry = load_registry(cfg, (overrides or {}).get("registry_path"))
    price_ids = price_sources(registry)
    price_reg = registry.loc[price_ids]
    raws = load_all(cfg, registry, overrides)
    ex = Extras(cfg, overrides)
    # species with no hand-made fictional series in this region get a generated one (labelled, tier C, low confidence)
    op_type = op_row.get("species_source_type")
    catalog, registry, gen_specs = scenario_species.augment(
        list(prof.species), brief.region, catalog, registry, raws, ex, as_of, cfg,
        source_type=op_type if op_type in ("wild_catch", "aquaculture") else None)
    if gen_specs:
        price_ids = price_sources(registry)
        price_reg = registry.loc[price_ids]
    gen_caveats = [f"{g.species} has no hand-made data in {g.region}, so its prices were generated for this scenario "
                   f"(seasonal shape from a {g.pattern.replace('_', ' ')} pattern, price level from {g.anchor})." for g in gen_specs]
    for sp in prof.species:
        st = str(catalog.loc[sp, "source_type"]) if sp in catalog.index else ""
        if op_type in ("wild_catch", "aquaculture") and st and st != op_type:
            gen_caveats.append(f"{sp} is usually {st.replace('_', ' ')}, which is unusual for a {op_row['label'].lower()}; "
                               f"the figures are for {st.replace('_', ' ')} {sp}.")
        elif not scenario_species.fits(sp, op_row.get("operation_id", ""), st or "wild_catch", cfg):
            gen_caveats.append(f"{sp} is not usually caught with the gear a {op_row['label'].lower()} uses; the figures are still for {sp}.")

    # the user's note: cleaned, scanned, never trusted
    clean_note = note_mod.sanitise(prof.free_text, cfg.NOTE_MAX_CHARS)
    scan = note_mod.scan(clean_note["text"], prof.species, prof.region, list(catalog.index), regions(catalog)) \
        if clean_note["text"] else {"flags": [], "injection_phrases": [], "out_of_scope": [], "conflicts": []}
    note_text = clean_note["text"]
    note_block = note_mod.block(note_text)
    forbidden = tuple(dict.fromkeys(scan["injection_phrases"]))
    # what the note says, read by Python: it fills empty goal/experience fields and adds constraints
    offer_names = [o.species for o in scenario_species.offers(catalog, brief.region, op_row, cfg)]
    facts = note_mod.extract(note_text, offer_names, regions(catalog), cfg.DATA_DIR) if note_text else note_mod.extract("", [], [], cfg.DATA_DIR)
    upd, differs = situation.merge(prof, facts)
    if upd:
        prof = prof.model_copy(update=upd)
        brief = brief.model_copy(update={"profile": prof})
    own_q_injected = bool(note_mod.matched_injection(prof.own_question))
    if own_q_injected:
        scan["flags"] = sorted(set(scan["flags"]) | {"untrusted_text_ignored"})
        forbidden = tuple(dict.fromkeys(list(forbidden) + note_mod.matched_injection(prof.own_question)))

    def covering_for(sp):
        return [s for s in price_ids if covers_series(raws[s], sp, brief.region)]

    covering = covering_for(brief.species)
    real_world: list[dict] = []
    if cfg.SCENARIO_REAL_CONTEXT:
        try:
            real_world = list(scenario_context.build(tuple(prof.species), brief.region))
        except Exception as err:                       # real-world background is optional; it must never break a run
            notes.append(f"real_world_context_unavailable:{type(err).__name__}")
    rw_agent = [it["agent_text"] for it in real_world if it.get("agent_text")]
    your_q = None
    web_on = bool(profile.get("web_research"))
    q_text = prof.own_question if (prof.own_question and not own_q_injected) else \
        (scenario_context.note_question(note_text) if (note_text and not scan["injection_phrases"]) else "")
    if not q_text and facts["asks"] and web_on and not scan["injection_phrases"]:
        # the note asked about something the scenario data cannot cover (loans, permits...): look for published options
        q_text = (f"What {facts['asks'][0]} options are available to a {op_row['label'].split(' (')[0].lower()} "
                  f"in {brief.region}, United States, for {', '.join(prof.species)}?")
    if q_text:
        try:
            your_q = scenario_context.answer_question(q_text, tuple(prof.species), brief.region, llm=llm,
                                                      web=web_on, cfg=cfg, mix=mix, run_ctx=ctx)
            if your_q.get("agent_text"):
                rw_agent.append(your_q["agent_text"])
        except Exception as err:                       # answering the note's question is optional; it must never break a run
            notes.append(f"your_question_unavailable:{type(err).__name__}")
    brief_detail = brief.model_dump()
    brief_detail["profile"] = {k: v for k, v in brief_detail["profile"].items() if k != "free_text"}
    tr.finish(ev, "done", f"{', '.join(prof.species)} in {brief.region}, as of {prof.as_of}",
              {"brief": brief_detail, "sources_with_rows": covering,
               "operation": op_row["label"], "question_type": qtype,
               "real_world_items": len(real_world),
               "note": {"length": clean_note["length"], "truncated": clean_note["truncated"],
                        "digest": note_mod.digest(note_text) if note_text else None, "flags": scan["flags"]},
               "overrides": {k: v for k, v in (overrides or {}).items() if v}})

    # ---- step 2: agent 1 ----------------------------------------------------
    state = {"calls": 0, "blocked": False}

    def ask_planner(problems):
        state["calls"] += 1
        e = tr.begin("agent1", state["calls"], "Asking the planner which sources to use")
        try:
            plan, schema_problems, call = agent1.ask(llm, ctx, models["agent1"], cfg.MAX_TOKENS["agent1"],
                                                     brief, price_reg, problems)
        except LLMError as err:
            state["blocked"] = True
            tr.finish(e, "failed", f"The AI planner call failed: {err}", {"error": str(err)}, err.call)
            return None, [f"AI call failed: {err}"]
        viol = schema_problems or (agent1.check_plan(plan, price_reg, covering) if plan else [])
        detail = {"plan": plan.model_dump() if plan else None, "violations": viol}
        if not viol:
            tr.finish(e, "done", f"Plan: {', '.join(plan.sources)} (primary {plan.primary_source_id})", detail, call)
        else:
            status = "retrying" if state["calls"] < 2 and not state["blocked"] else "warning"
            tr.finish(e, status, "The plan broke the rules: " + " ".join(viol), detail, call)
        return plan, viol

    def python_default(reason: str):
        plan = agent1.default_plan(price_reg, covering)
        e = tr.begin("agent1", state["calls"] + 1)
        tr.finish(e, "fallback", f"Python's default plan was used ({reason}): {', '.join(plan.sources)}",
                  {"python_default_plan": True, "plan": plan.model_dump()})
        notes.append("python_default_plan")
        return plan

    if covering == [scenario_species.GEN_SOURCE]:
        # only the generated series exists for this pair: there is nothing for the planner to choose
        plan, viol = agent1.default_plan(price_reg, covering), []
        e = tr.begin("agent1", 1)
        tr.finish(e, "done", f"Only the generated series covers {brief.species} in {brief.region}, so no planner call was needed.",
                  {"plan": plan.model_dump(), "skipped": "generated_series_only"})
    else:
        plan, viol = ask_planner(None)
    if viol and not state["blocked"] and state["calls"] < 2:
        plan, viol = ask_planner(viol)
    if viol:
        plan = python_default("the planner could not produce a valid plan")
    if not plan.sources:
        e = tr.begin("gate")
        tr.finish(e, "failed", "No approved source has data for this market.", {})
        return _finish_failed(tr, ctx, brief, registry, cfg, save, "No approved source has data for this market.")

    # ---- step 3: gate -------------------------------------------------------
    def do_gate(sp, sources, primary, attempt):
        e = tr.begin("gate", attempt, "Checking the data" + (f" for {sp}" if len(prof.species) > 1 else ""))
        g = run_gate(cfg, registry, raws, sources, sp, brief.region, as_of, catalog, primary)
        if g.primary_id == scenario_species.GEN_SOURCE:
            g.series_flags["generated_series"] = 1
            g.series_flags.pop("single_source", None)      # one generated series is expected, not a cross-check gap
        flags = sorted(g.series_flags)
        who = f"{sp}: " if len(prof.species) > 1 else ""
        if g.hard_failure:
            tr.finish(e, "warning", who + "Hard failure: " + "; ".join(g.failure_reasons), g.summary())
        else:
            head = f"{len(g.usable_ids)} usable source(s), primary {g.primary_id}; flags: {', '.join(flags) or 'none'}"
            tr.finish(e, "warning" if flags else "done", who + head, g.summary())
        return g

    gate = do_gate(brief.species, plan.sources, plan.primary_source_id, 1)
    gate_attempt = 1
    if gate.hard_failure and state["calls"] < 2 and not state["blocked"]:
        plan2, viol2 = ask_planner(["The data check failed: " + " ".join(gate.failure_reasons)])
        if viol2:
            plan2 = python_default("the retried plan was invalid")
        gate_attempt = 2
        gate = do_gate(brief.species, plan2.sources, plan2.primary_source_id, 2)
    if gate.hard_failure:
        if FALLBACK_SOURCE in registry.index and FALLBACK_SOURCE in covering:
            e = tr.begin("gate", gate_attempt + 1, "Falling back to labelled sample data")
            gate = run_gate(cfg, registry, raws, [FALLBACK_SOURCE], brief.species, brief.region, as_of,
                            catalog, FALLBACK_SOURCE)
            gate.series_flags.pop("single_source", None)
            gate.series_flags["fallback_sample_data"] = 1
            tr.finish(e, "fallback" if not gate.hard_failure else "failed",
                      "No approved source could be verified, so labelled sample data is used (confidence capped at low)."
                      if not gate.hard_failure else "Even the sample data failed the checks.", gate.summary())
        if gate.hard_failure:
            return _finish_failed(tr, ctx, brief, registry, cfg, save,
                                  "No source passed the verification checks, so no recommendation can be made.",
                                  gate=gate)
    gates = {brief.species: gate}
    skipped: list[str] = []
    for sp in prof.species[1:]:
        cov = covering_for(sp)
        dplan = agent1.default_plan(price_reg, cov)
        g2 = do_gate(sp, dplan.sources, dplan.primary_source_id, 1)
        if g2.hard_failure:
            notes.append(f"species_skipped:{sp}")
            skipped.append(sp)
            continue
        gates[sp] = g2

    price_flags: set[str] = set()
    ratings, reasons = [], []
    for g in gates.values():
        price_flags |= set(g.series_flags)
        t = compute_trust(set(g.series_flags), g.usable_tiers())
        ratings.append(t["rating"])
        reasons += [r for r in t["reasons"] if r not in reasons]
    trust = {"rating": _worst(ratings), "reasons": reasons}
    flags = set(price_flags)
    if skipped:
        flags.add("species_skipped")      # named in the caveats; never dropped silently

    # ---- step 4: analytics --------------------------------------------------
    e = tr.begin("analytics")
    results = []
    for sp, g in gates.items():
        results.append(analyse_species(sp, prof, g, registry, catalog, ex, as_of, op_row, cfg))
    stats = merge(results)
    extra_flags = set().union(*[r.flags for r in results]) | set(scan["flags"])
    flags |= extra_flags
    result0 = results[0]
    decision = decide(stats, qtype, cfg)
    forbidden = tuple(dict.fromkeys(list(forbidden) + [p for r in results for p in r.quality.get("injection_phrases", [])]))
    tr.finish(e, "done", f"{len(stats)} statistics computed ({qtype.replace('_', ' ')}); direction: {decision['direction']}",
              {"stats": [s.model_dump() for s in stats], "decision": decision,
               "channels": {r.species: {"channel": r.channel, "source": r.source_id} for r in results},
               "extra_flags": sorted(extra_flags)})

    # ---- steps 5 and 6: agent 2 and the grounding check ---------------------
    analysis, violations, cautious, rejected = None, None, False, None
    for attempt in (1, 2):
        e = tr.begin("agent2", attempt, "Asking the analyst to interpret the statistics")
        try:
            cand, shape_problems, call = agent2.ask(llm, ctx, models["agent2"], cfg.MAX_TOKENS["agent2"], prof,
                                                    stats, trust, flags, cfg, violations, decision, note_block,
                                                    op_row["label"], real_world=rw_agent,
                                                    situation={"note_facts": situation.agent_facts(facts), "user_question": q_text})
        except LLMError as err:
            tr.finish(e, "failed", f"The AI analyst call failed: {err}", {"error": str(err)}, err.call)
            cautious = True
            break
        tr.finish(e, "done" if cand else "warning",
                  (cand.headline if cand else "The analyst's answer had the wrong shape."),
                  {"analysis": cand.model_dump() if cand else None}, call)
        g = tr.begin("grounding", attempt, "Checking every number and rule")
        viol = shape_problems or check_analysis(cand, stats, cfg, qtype, forbidden,
                                                {Decimal(repr(float(prof.volume_lb_per_month)))})
        if not viol:
            tr.finish(g, "done", "All grounding checks passed.", {"violations": []})
            analysis = cand
            break
        violations, rejected = viol, cand
        last = attempt == 2
        tr.finish(g, "failed" if last else "retrying",
                  f"{len(viol)} problem(s) found" + ("." if last else "; asking the analyst once more."),
                  {"violations": viol})
    if analysis is None:
        cautious = True
        analysis = template_analysis(stats, prof, cfg, with_lens=False, qtype=qtype, op_label=op_row["label"])
        flags.add("cautious_answer")
        e = tr.begin("grounding", 3)
        unv = unverified.build(rejected, violations or [])
        tr.finish(e, "fallback", "The analyst's explanation could not be verified; using rule-based claims."
                  + (" The unverified explanation is shown separately with a warning." if unv else ""),
                  {"cautious_answer": True, "unverified_shown": bool(unv)})
    else:
        unv = None
    if not analysis.timing_window.strip():
        # The window is deterministic: Python supplies it when the analyst leaves it out, and says so.
        analysis.timing_window = timing_window(analysis.direction, stats)
        last_check = [ev for ev in tr.events if ev["step"] == "grounding"][-1]
        last_check["detail"] = {**last_check["detail"],
                                "python_notes": last_check["detail"].get("python_notes", []) + ["timing_window_filled"]}
    if qtype == "sell_or_hold" and len(results) == 1:
        analysis.driver_tags = sorted(expected_tags(stats, analysis.direction, cfg))   # derived by rule
    else:
        analysis.driver_tags = []

    # ---- step 7: summary ----------------------------------------------------
    sit_notes = situation.notes(prof, analysis.direction, analysis.timing_window, qtype, trust["rating"],
                                result0.tables, facts)
    asks = sorted(set(scan["out_of_scope"]) | set(facts["asks"]))
    ask_line = []
    if asks:
        flags.add("note_out_of_scope")
        ask_line.append("The scenario data does not cover that part of your note; "
                        + ("it was passed to the researcher, see Your question." if web_on and your_q else
                           "tick web research to look for published information on it."))
    if differs:
        ask_line.append("Where your note and the form differ, the form was used: " + "; ".join(differs) + ".")
    note_info = {"out_of_scope": asks, "conflicts": scan["conflicts"], "skipped_species": skipped,
                 "extra_caveats": gen_caveats + ask_line}
    caveats = caveats_for(flags, note_info)
    e = tr.begin("summary", 1, "Writing the plain-language summary")
    species_label = ", ".join(r.species for r in results)
    recommendation = recommendation_sentence(analysis.direction, qtype, species_label, analysis.timing_window, stats)
    user = summary_agent.build_user(species_label, brief.region, analysis.direction, analysis.timing_window,
                                    analysis.claims, analysis.actions, trust, caveats, qtype, note_block,
                                    op_row["label"], analysis.headline, recommendation, real_world=rw_agent,
                                    situation={"goal": prof.goal, "constraints": list(prof.constraints),
                                               "lens_note": analysis.lens_notes.your_situation})
    summary_md, call, problems = "", None, []
    try:
        summary_md, call = summary_agent.ask(llm, ctx, models["summary"], cfg.MAX_TOKENS["summary"], user)
        problems = (check_summary(summary_md, trust["rating"], analysis.claims, forbidden, recommendation,
                                  analysis.direction) if summary_md else ["empty answer"])
    except LLMError as err:
        problems = [f"AI call failed: {err}"]
        call = err.call
    if problems:
        flags.add("template_summary")
        caveats = caveats_for(flags, note_info)
        summary_md = template_summary(analysis.direction, analysis.timing_window, species_label, analysis.claims,
                                      analysis.actions, trust["rating"], trust["reasons"], caveats, qtype, stats)
        tr.finish(e, "fallback", "The written summary failed its checks, so a fixed template was used.",
                  {"problems": problems, "template_summary": True}, call)
    else:
        tr.finish(e, "done", "Summary passed all checks.", {"markdown": summary_md}, call)

    # ---- step 8: report -----------------------------------------------------
    e = tr.begin("report")
    rep = report_mod.build_report(brief, as_of, analysis, summary_md, trust, flags, gates, registry, stats, results,
                                  tr, ctx, cautious, decision, op_row, clean_note, scan, note_info)
    if unv:
        rep["unverified"] = unv
    if your_q:
        rep["your_question"] = {k: v for k, v in your_q.items() if k != "agent_text"}
    if facts["taken"] or sit_notes or prof.goal or prof.constraints or prof.own_question:
        rep["your_situation"] = {"taken": facts["taken"], "notes": sit_notes, "applied": sorted(upd),
                                 "goal": prof.goal, "constraints": list(prof.constraints), "experience": prof.experience,
                                 "own_question": prof.own_question, "question_matched": prof.question_matched,
                                 "question_label": QUESTION_LABELS.get(qtype, "")}
    if real_world:
        rep["real_world"] = [{"species": it["species"], "text": it["text"], "source": it["source"]} for it in real_world]
    tr.finish(e, "done", "Report ready.", {})
    rep["cost"] = report_mod.cost_block(tr, ctx)
    result = {"run_id": tr.run_id, "status": "ok", "report": rep, "events": tr.events, "notes": notes,
              "calls": ctx.calls, "paid_calls": ctx.paid_calls, "gate": gate.summary(),
              "gates": {k: v.summary() for k, v in gates.items()},
              "stats": [s.model_dump() for s in stats], "analysis": analysis.model_dump(),
              "decision": decision, "flags": sorted(flags), "trust": trust, "question_type": qtype}
    return _save(result, cfg) if save else result


def _finish_failed(tr, ctx, brief, registry, cfg, save, message, gate: Optional[GateReport] = None) -> dict:
    result = {"run_id": tr.run_id, "status": "failed", "message": message, "events": tr.events, "notes": [],
              "calls": ctx.calls, "paid_calls": ctx.paid_calls, "gate": gate.summary() if gate else None,
              "report": {"fictional_notice": report_mod.FICTIONAL_LINE, "direction": "insufficient_data",
                         "headline": message, "summary_md": message, "confidence": {"rating": "low", "reasons": [message]},
                         "caveats": [], "provenance": [], "charts": None, "cost": report_mod.cost_block(tr, ctx)},
              "stats": [], "analysis": None, "flags": [], "trust": {"rating": "low", "reasons": [message]}}
    return _save(result, cfg) if save else result


def _save(result: dict, cfg: Config) -> dict:
    Path(cfg.RUNS_DIR).mkdir(parents=True, exist_ok=True)
    p = Path(cfg.RUNS_DIR) / f"{result['run_id']}.json"
    stored = json.loads(json.dumps(result, default=str))
    if (stored.get("report") or {}).get("heard"):
        stored["report"]["heard"]["text"] = "[not stored]"       # the user's note is never written to disk
    if (stored.get("report") or {}).get("your_situation"):
        stored["report"]["your_situation"] = dict(stored["report"]["your_situation"], taken=["[not stored]"], own_question="[not stored]")
    if (stored.get("report") or {}).get("your_question"):
        stored["report"]["your_question"] = dict(stored["report"]["your_question"], question="[not stored]", answer_md="[not stored]")
    p.write_text(json.dumps(stored, indent=1))
    result["saved_to"] = str(p)
    return result
