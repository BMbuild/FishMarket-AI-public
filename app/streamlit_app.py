"""FishMarket AI: Streamlit demo. Run with:  streamlit run app/streamlit_app.py

The app reads app/presets.json only (never the tests-only folder). All data is fictional."""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

sys.path.insert(0, str(ROOT / "app"))
import extra_pages  # noqa: E402
import theme  # noqa: E402
from fishmarket import note as note_mod, scenario_species  # noqa: E402
from fishmarket.config import DEFAULT, QUESTION_LABELS  # noqa: E402
from fishmarket.events import AI_STEPS, STEPS  # noqa: E402
from fishmarket.llm import LLM, LLMError  # noqa: E402
from fishmarket.loader import overrides_from_manifest, planted_cases  # noqa: E402
from fishmarket.pipeline import ProfileError, run  # noqa: E402
from fishmarket.registry import (load_catalog, load_operations, load_segments, regions,  # noqa: E402
                                 species_for_region)

BANNER = "Fictional data, not real market prices."
STEP_TITLES = {"profile": "1. Profile", "agent1": "2. Retrieval planner", "gate": "3. Verification gate",
               "analytics": "4. Analytics", "agent2": "5. Analyst", "grounding": "6. Grounding check",
               "summary": "7. Summary writer", "report": "8. Report"}
STATUS_STYLE = {"pending": ("⚪", "#a8bfbe"), "running": ("🔵", "#64b5f6"), "done": ("🟢", "#65d49a"),
                "warning": ("🟠", "#ffb45e"), "retrying": ("🟡", "#ffd166"), "failed": ("🔴", "#ff7b72"),
                "fallback": ("🟣", "#c39bff")}
MODE_LABELS = {"auto": "Auto (use saved answers, call the AI when missing)",
               "replay": "Replay (saved answers only, free and safe)",
               "live": "Live (always call the AI)",
               "fake": "Offline demo (scripted stand-in, no AI)"}


@st.cache_data
def _presets() -> list[dict]:
    return json.loads(DEFAULT.PRESETS_PATH.read_text())


@st.cache_data
def _cases() -> list[dict]:
    return planted_cases(DEFAULT)


def _catalog():
    return load_catalog(DEFAULT)


def _ops():
    return load_operations(DEFAULT)


EXPERIENCE = ["", "new", "some", "experienced"]
GOALS = ["", "maximize price", "steady income", "reduce risk", "grow volume"]
CONSTRAINTS = ["limited storage", "cash needed soon", "no boat access", "seasonal workers", "small crew", "single buyer"]


def apply_preset(pid: str) -> None:
    preset = next(x for x in _presets() if x["id"] == pid)
    p = preset["profile"]
    st.session_state["operation"] = p.get("operation_type") or p.get("business_type")
    st.session_state["region"] = p["region"]
    st.session_state["species"] = list(p["species"])
    st.session_state["customer_segment"] = p["customer_segment"]
    st.session_state["volume"] = float(p["volume_lb_per_month"])
    st.session_state["storage"] = p.get("storage", "none")
    st.session_state["question_type"] = p.get("question_type", "sell_or_hold")
    st.session_state["free_text"] = p.get("free_text", "")
    st.session_state["experience"] = p.get("experience", "")
    st.session_state["goal"] = p.get("goal", "")
    st.session_state["constraints"] = list(p.get("constraints", []))
    for k in ("species_typed", "own_question", "goal_typed", "constraints_typed"):
        st.session_state[k] = ""
    for c in _cases():
        st.session_state[f"pp_{c['case_id']}"] = c["case_id"] in preset["planted_cases"]


def apply_note(facts: dict) -> None:
    """'Fill the form from my note': copy what Python read out of the note into the form (the user can still edit)."""
    if facts.get("region"):
        st.session_state["region"] = facts["region"]
    if facts.get("species"):
        st.session_state["species"] = list(dict.fromkeys(facts["species"]))[:DEFAULT.MAX_SPECIES]
    if facts.get("storage"):
        st.session_state["storage"] = facts["storage"]
    if facts.get("volume_lb_per_month"):
        st.session_state["volume"] = float(facts["volume_lb_per_month"])
    if facts.get("segment"):
        st.session_state["customer_segment"] = facts["segment"]
    if facts.get("goal") in GOALS:
        st.session_state["goal"] = facts["goal"]
    if facts.get("experience") in EXPERIENCE:
        st.session_state["experience"] = facts["experience"]
    known = [c for c in facts.get("constraints", []) if c in CONSTRAINTS]
    other = [c for c in facts.get("constraints", []) if c not in CONSTRAINTS]
    if known:
        st.session_state["constraints"] = list(dict.fromkeys(list(st.session_state.get("constraints", [])) + known))
    if other:
        st.session_state["constraints_typed"] = "; ".join(other)
    if facts.get("questions"):
        st.session_state["question_type"] = "own_question"
        st.session_state["own_question"] = facts["questions"][0]


def init_state() -> None:
    first = _presets()[0]
    if "region" not in st.session_state:
        apply_preset(first["id"])
    st.session_state.setdefault("result", None)


def card_html(step: str, attempts: dict) -> str:
    ai = step in AI_STEPS
    latest = attempts[max(attempts)] if attempts else {"status": "pending", "headline": "", "cost_usd": 0.0}
    icon, colour = STATUS_STYLE.get(latest["status"], STATUS_STYLE["pending"])
    tag = "AI agent" if ai else "Python check"
    tag_bg = "#ede7f6" if ai else "#e6f4ea"
    border = "#6c5ce7" if ai else "#34a853"
    lines = []
    for n in sorted(attempts):
        e = attempts[n]
        i2, c2 = STATUS_STYLE.get(e["status"], STATUS_STYLE["pending"])
        cost = f" · ${e['cost_usd']:.4f}" if e.get("cost_usd") else (" · saved answer" if e.get("cache") == "hit" else "")
        label = f"attempt {n}: " if len(attempts) > 1 else ""
        lines.append(f"<div style='color:{c2};font-size:0.92rem'>{i2} {label}{html.escape(e.get('headline', ''))}"
                     f"<span style='color:#5f6368'>{cost}</span></div>")
    body = "".join(lines) or "<div style='color:#9aa0a6;font-size:0.92rem'>Waiting...</div>"
    return (f"<div style='border-left:5px solid {border};padding:6px 12px;margin:4px 0;background:rgba(128,128,128,0.07);"
            f"border-radius:4px'><b>{STEP_TITLES[step]}</b> "
            f"<span style='background:{tag_bg};color:#202124;border-radius:10px;padding:1px 8px;font-size:0.75rem'>{tag}</span>"
            f"{body}</div>")


def active_cases() -> list[str]:
    """Checked planted cases, skipping any that replace a source an earlier checked case already replaced."""
    used, out = {}, []
    for c in _cases():
        targets = c["replaces"].split("+")
        if st.session_state.get(f"pp_{c['case_id']}") and not any(r in used for r in targets):
            for r in targets:
                used[r] = c["case_id"]
            out.append(c["case_id"])
    return out


def make_llm(mode: str, overrides):
    if mode == "fake":
        from fishmarket.fake_agents import fake_llm
        return fake_llm(DEFAULT, overrides)
    return LLM(DEFAULT, mode=mode)


def sidebar():
    st.sidebar.header("Settings")
    mode = st.sidebar.selectbox("AI mode", list(MODE_LABELS), format_func=lambda m: MODE_LABELS[m], key="mode")
    mix = st.sidebar.radio("Model mix", ["dev", "final"], key="mix",
                           help="dev: all small models (cheapest). final: stronger analyst for the demo.")
    st.sidebar.subheader("Presets")
    for p in _presets():
        st.sidebar.button(f"{p['id']}  {p['name']}", key=f"preset_{p['id']}", on_click=apply_preset, args=(p["id"],))
    st.sidebar.subheader("Budget")
    budget = LLM(DEFAULT, mode="replay")
    spent = budget.ledger.total()
    st.sidebar.metric("Spent so far", f"${spent:.2f}")
    st.sidebar.metric("Remaining before the safety stop", f"${budget.remaining_budget():.2f}")
    if budget.ledger.bad_lines():
        st.sidebar.error(f"The spend ledger has {budget.ledger.bad_lines()} unreadable line(s), so total spend is "
                         "unknown. Live calls are blocked until it is fixed.")
    st.sidebar.progress(min(1.0, spent / DEFAULT.GLOBAL_STOP_USD))
    st.sidebar.caption(f"Safety stop at ${DEFAULT.GLOBAL_STOP_USD:.0f}; each run is capped at ${DEFAULT.PER_RUN_LIMIT_USD:.2f}.")
    return mode, mix


def profile_form() -> dict:
    cat, ops = _catalog(), _ops()
    segs = load_segments(DEFAULT)
    st.markdown("### 1. What do you do?")
    op_id = st.selectbox("Type of operation", list(ops.index), key="operation",
                         format_func=lambda o: ops.loc[o, "label"])
    op = ops.loc[op_id]
    st.caption(str(op["description"]))
    st.markdown("### 2. Where and what?")
    c1, c2 = st.columns(2)
    with c1:
        region = st.selectbox("US region", regions(cat), key="region")
    offers = scenario_species.offers(cat, region, op.to_dict(), DEFAULT)
    info = {o.species: o for o in offers}
    options = [o.species for o in offers]
    keep = [s for s in st.session_state.get("species", []) if s in info]
    if st.session_state.get("species_region") != region:
        # new region: keep only species found there; picks from other regions stay only while the region is unchanged
        keep = [s for s in keep if info[s].group != "other"]
        st.session_state["species_region"] = region
    st.session_state["species"] = keep[:DEFAULT.MAX_SPECIES] or options[:1]

    def label(sp: str) -> str:
        o = info.get(sp)
        if o is None:
            return sp
        tag = {"suggested": "suits your operation", "region": f"in {region}", "other": "other regions"}[o.group]
        return f"{sp}  ·  {tag}" + ("" if o.handmade else "  ·  generated data")

    with c2:
        species = st.multiselect(f"Species (up to {DEFAULT.MAX_SPECIES})", options, key="species", format_func=label,
                                 help="Best fits for your operation are listed first, then the rest of your region, then every other "
                                      "species. Species without hand-made demo data get a generated series, clearly labelled.")
    extra_sp = st.text_input("Not in the list? Type species names (separate with commas)", key="species_typed",
                             placeholder="For example: Golden king crab, Spot prawn")
    typed = [scenario_species.clean_name(x) for x in extra_sp.split(",") if x.strip()]
    species = list(dict.fromkeys(list(species) + [t for t in typed if t]))[:max(DEFAULT.MAX_SPECIES, 1)]
    if any(not info.get(sp) or not info[sp].handmade for sp in species):
        st.caption("Species marked 'generated data' have no hand-made demo series in this region, so Python generates one "
                   "(price level from real NOAA landings where they exist). Confidence is capped at low.")
    st.markdown("### 3. Your customers and volume")
    c3, c4, c5 = st.columns(3)
    with c3:
        seg = st.selectbox("Customer segment", list(segs.index), key="customer_segment",
                           format_func=lambda s: segs.loc[s, "label"])
    with c4:
        volume = st.number_input("Monthly volume (lb)", min_value=0.0, step=500.0, key="volume")
    with c5:
        storage = st.selectbox("Storage you have", ["none", "chilled", "frozen"], key="storage")
    st.markdown("### 4. What do you want to know?")
    allowed = list(op["allowed"]) + ["own_question"]
    if st.session_state.get("question_type") not in allowed:
        st.session_state["question_type"] = op["default_question_type"]
    qtype = st.selectbox("Question", allowed, key="question_type",
                         format_func=lambda q: QUESTION_LABELS.get(q, "Ask my own question..."))
    if len(species) > 1 and qtype in ("best_months", "compare_markets", "best_buyer_type"):
        st.warning("This question works on one species at a time. Pick one species, or ask sell-or-hold, which answers each species.")
    own_q = ""
    if qtype == "own_question":
        own_q = st.text_input("Your question", key="own_question", max_chars=300,
                              placeholder="For example: When do snow crab prices peak? or Can I get a loan for more pots?",
                              help="We run the closest calculation, and answer the question itself from real U.S. data "
                                   "(or the web, if you tick the box below).")
    st.markdown("### 5. Tell us about you (optional)")
    note = st.text_area("Tell us about you and your situation (optional)", key="free_text", max_chars=DEFAULT.NOTE_MAX_CHARS,
                        placeholder="For example: I run a two-boat lobster operation. My freezer is small. "
                                    "A restaurant client wants steady supply through winter.",
                        help="Python reads species, storage, volume, customers, goals, constraints and questions out of this. "
                             "It shapes the advice and adds context; it never changes the scenario's numbers. Do not type contact details.")
    facts = None
    if note.strip():
        facts = note_mod.extract(note_mod.sanitise(note, DEFAULT.NOTE_MAX_CHARS)["text"], options + typed, regions(cat), DEFAULT.DATA_DIR)
        if facts["taken"]:
            st.caption("What we took from your note: " + "; ".join(facts["taken"]))
            st.button("Fill the form from my note", key="apply_note", on_click=apply_note, args=(facts,),
                      help="Copies what your note says into the form fields above and below. You can still change them.")
    web_research = st.checkbox("If the real data can't answer my question, let the researcher search the web (up to 3 searches)",
                               key="web_research", value=False,
                               help="Off by default. Needs a live AI mode. Official sites first, then the open web. Only exact quotes "
                                    "with links are kept; they are shown apart from the scenario and never change its numbers. "
                                    "Topics the scenario can't cover (loans, permits, insurance...) are researched this way too.")
    c6, c7 = st.columns(2)
    with c6:
        experience = st.selectbox("Experience", EXPERIENCE, key="experience")
    with c7:
        goal = st.selectbox("Main goal", GOALS, key="goal")
    goal_typed = st.text_input("Or describe your goal in your own words", key="goal_typed", max_chars=80)
    constraints = st.multiselect("Constraints", CONSTRAINTS, key="constraints")
    cons_typed = st.text_input("Other constraints (separate with semicolons)", key="constraints_typed", max_chars=240,
                               placeholder="For example: only one buyer; boat in the yard until March")
    constraints = list(constraints) + [c.strip() for c in cons_typed.split(";") if c.strip()]
    with st.expander("Planted data problems (to show the verification layer working)"):
        used = {}
        for c in _cases():
            clash = any(r in used for r in c["replaces"].split("+"))
            st.checkbox(f"{c['case_id']}: {c['injected']}", key=f"pp_{c['case_id']}", disabled=clash,
                        help=(f"Disabled because another checked case already replaces {c['replaces']}." if clash else None))
            if not clash and st.session_state.get(f"pp_{c['case_id']}"):
                for r in c["replaces"].split("+"):
                    used[r] = c["case_id"]
    return {"operation_type": op_id, "region": region, "species": list(species), "customer_segment": seg,
            "volume_lb_per_month": volume, "storage": storage, "question_type": qtype, "own_question": own_q,
            "free_text": note, "web_research": bool(web_research), "experience": experience,
            "goal": goal_typed.strip() or goal, "constraints": constraints, "as_of": DEFAULT.AS_OF_DEFAULT}


DIRECTION_WORDS = {"hold": "HOLD", "sell_now": "SELL NOW", "buy_now": "BUY NOW", "wait": "WAIT",
                   "no_clear_signal": "NO CLEAR SIGNAL", "insufficient_data": "NOT ENOUGH DATA", "per_species": "ONE ANSWER PER PRODUCT"}


def _table(rows: list[dict], cols: dict) -> None:
    st.dataframe(pd.DataFrame([{label: r.get(k) for k, label in cols.items()} for r in rows]), hide_index=True,
                 use_container_width=True)


def show_species_panels(rep: dict) -> None:
    for sp in rep["species"]:
        q, t = sp["quality"], sp["tables"]
        st.markdown(f"#### {sp['species']}")
        share = q.get("verified_share")
        st.markdown(f"**Quality records:** {q['status']}"
                    + (f" ({share * 100:.0f}% verified, modal grade {q.get('modal_grade')}, "
                       f"median freshness {q.get('median_freshness_days'):.0f} days)" if share is not None else "")
                    + ". Quality is reported only as recorded; it is never a safety certificate.")
        if "best_months" in t:
            st.markdown("**Best months (open season only)**")
            _table(t["best_months"]["top"], {"month": "Month", "score": "Score"})
        if "markets" in t:
            st.markdown("**Markets ranked by net price (USD per lb, after fees and freight)**")
            _table(t["markets"]["ranking"], {"name": "Market", "region": "Region", "mean3_price": "3-month price",
                                              "fee_pct": "Fee %", "freight": "Freight", "net_price": "Net price"})
            if t["markets"]["excluded"]:
                st.markdown("**Left out as out of date**")
                _table(t["markets"]["excluded"], {"name": "Market", "reason": "Why"})
            try:
                theme.chart("bar", pd.DataFrame(t["markets"]["ranking"]).set_index("name")["net_price"], "Market", "Net price (USD per lb)")
            except Exception:
                pass
        if "buyers" in t:
            b = t["buyers"]
            st.markdown(f"**Buyer types ranked by net price** (grade used: {b['grade_used']}"
                        f"{'' if b['grade_verified'] else ', assumed because none is verified'})")
            _table(b["ranking"], {"label": "Buyer type", "net_price": "Net price", "payment_days": "Pays in (days)"})
            if b["excluded"]:
                st.caption("Not shown: " + "; ".join(f"{k.replace('_', ' ')} ({v})" for k, v in b["excluded"].items()))
        if "hold" in t:
            h = t["hold"]
            st.markdown(f"**Holding economics ({h['storage']}):** net {h['net_gain_pct']:.1f}% over {h['months']} month(s)"
                        + (" - this product would not keep that long." if h["shelf_exceeded"] else "."))
        if "costs" in t:
            c = t["costs"]
            st.markdown("**Input cost changes (year over year)**")
            _table([{"cost": k.replace("_", " "), "pct": v} for k, v in c["per_type"].items()], {"cost": "Cost", "pct": "% change"})
            if c["incomplete"]:
                st.caption("Not enough data (not estimated): " + ", ".join(x.replace("_", " ") for x in c["incomplete"]))


def show_real_world(items: list | None) -> None:
    """Real U.S. data about the same species, kept apart from the fictional scenario numbers."""
    if not items:
        return
    with st.expander("Real U.S. data for these species (separate from this fictional scenario)"):
        st.caption("These figures come from real public data (NOAA landings, stock assessments, OECD). The recommendation above is "
                   "based only on the fictional demo data; the two are never combined.")
        for it in items:
            st.markdown(f"- **{it['species']}:** {it['text']}  \n  <span style='font-size:0.85em;opacity:0.75'>Source: {html.escape(it['source'])}</span>",
                        unsafe_allow_html=True)


def show_your_question(q: dict | None) -> None:
    """The question the user typed in the text box, answered from real data (or web quotes), apart from the scenario."""
    if not q:
        return
    st.markdown("**Your question**")
    st.caption(q["question"])
    pills = " ".join(theme.origin_pill(o) for o in q.get("origins", []))
    conf = f" &nbsp; confidence <b>{html.escape(str(q['confidence']))}</b>" if q.get("confidence") else ""
    if pills or conf:
        st.markdown(f"<div class='fm-card'>{pills}{conf}</div>", unsafe_allow_html=True)
    st.markdown(q["answer_md"])
    if q.get("verdict") in ("cannot", "clarify") and not q.get("web_tried"):
        st.caption("The real data here can't answer this. Tick 'let the researcher search the web' above and run again to look it up.")
    if q.get("web_tried") and not q.get("web_searches"):
        st.caption("Web research was ticked but did not run (it needs a live AI mode and budget).")
    if q.get("citations"):
        with st.expander("Sources for this answer"):
            for c in q["citations"]:
                st.write("- " + c)
    st.caption("This answer is separate from the fictional scenario; the two are never combined.")


def _md(text: str) -> str:
    """User-written text shown as plain words in markdown (no links, emphasis or HTML)."""
    return re.sub(r"([\\`*_{}\[\]()<>#|])", r"\\\1", str(text))


def show_your_situation(s: dict | None) -> None:
    """What the run took from the user's note, goal and constraints, and Python's notes tying the answer to them."""
    if not s:
        return
    st.markdown("**Your situation**")
    lines = []
    if s.get("own_question"):
        lines.append(f"Your question was answered with: *{s['question_label']}*" if s.get("question_matched") else
                     f"Your question did not match one of the calculations, so *{s['question_label']}* was run, "
                     "and the question itself is answered below under Your question.")
    if s.get("goal"):
        lines.append(f"Goal: {_md(s['goal'])}")
    if s.get("constraints"):
        lines.append("Constraints: " + ", ".join(_md(c) for c in s["constraints"]))
    if s.get("taken"):
        lines.append("From your note: " + "; ".join(_md(t) for t in s["taken"]))
    if s.get("applied"):
        lines.append("Filled in from your note: " + ", ".join(s["applied"]))
    for x in lines:
        st.markdown("- " + x)
    for n in s.get("notes", []):
        st.info(n)


def show_unverified(u: dict | None) -> None:
    """The AI explanation that failed its checks, shown under the verified answer with a clear warning."""
    if not u:
        return
    with st.expander("AI analyst's explanation (not verified)"):
        st.warning(u["disclaimer"] + " Checks it failed: " + "; ".join(u["problems"]) + ".")
        if u.get("headline"):
            st.markdown(f"*{u['headline']}*")
        for c in u["claims"]:
            st.markdown(("- \u26a0\ufe0f " if c["failed_check"] else "- ") + c["text"] + (" *(failed a check)*" if c["failed_check"] else ""))


def show_result(res: dict) -> None:
    rep = res["report"]
    if res["status"] != "ok":
        st.error(rep["summary_md"])
        return
    d = rep["direction"]
    if d == "ranking":
        st.subheader(QUESTION_LABELS.get(rep["question_type"], "Result"))
    else:
        word = DIRECTION_WORDS.get(d, d.upper())
        st.subheader(f"{word}  {rep['timing_window'] if d in ('hold', 'wait') else ''}".strip())
    if rep["headline"]:
        st.caption(rep["headline"])
    if d == "per_species":
        for ser, dd in rep["directions_by_series"].items():
            st.markdown(f"- **{ser.split('|')[0]}:** {DIRECTION_WORDS.get(dd, dd)}")
    if rep.get("heard"):
        h = rep["heard"]
        st.markdown("**What we heard from you**")
        st.info(h["text"] + (" (shortened)" if h["truncated"] else ""))
    st.markdown(rep["summary_md"])
    conf = rep["confidence"]
    {"high": st.success, "medium": st.warning, "low": st.error}[conf["rating"]](
        f"Confidence: {conf['rating']}. " + " ".join(conf["reasons"]))
    if rep["caveats"]:
        st.markdown("**Caveats**\n" + "\n".join(f"- {c}" for c in rep["caveats"]))
    show_unverified(rep.get("unverified"))
    show_your_situation(rep.get("your_situation"))
    show_your_question(rep.get("your_question"))
    show_real_world(rep.get("real_world"))
    show_species_panels(rep)
    st.markdown("**Where the numbers came from**")
    prov = pd.DataFrame([{"Product": p.get("species", ""), "Source": p["source_id"], "Tier": p["tier"],
                          "Last updated": p["last_updated"], "Rows used": p["rows_used"], "Status": p["status"],
                          "Flags": ", ".join(f"{k} ({v})" for k, v in p["flags"].items())} for p in rep["provenance"]])
    st.dataframe(prov, hide_index=True, use_container_width=True)
    ch = rep["charts"]
    hist = pd.DataFrame(ch["history"])
    hist["date"] = pd.to_datetime(hist["date"])
    st.markdown("**Price history (USD per lb, " + rep["species"][0]["channel"].replace("_", " ") + ")**")
    theme.chart("line", hist.set_index("date")["price"], "Month", "Price (USD per lb)")
    if ch["seasonal_index"]:
        st.markdown("**Seasonal price index** (1.0 is an average month; this month and the next three highlighted)")
        rows = []
        for i, m in enumerate(ch["months"]):
            role = "this month" if i == ch["now_index"] else "next 3 months" if i in ch["next3_indexes"] else "other"
            rows.append({"month": m[:3], "index": ch["seasonal_index"][i], "window": role, "order": i})
        df = pd.DataFrame(rows)
        try:
            import altair as alt
            chart = alt.Chart(df).mark_bar().encode(
                x=alt.X("month:N", sort=list(df["month"]), title="Month"), y=alt.Y("index:Q", title="Seasonal price index (1.0 = average month)"),
                color=alt.Color("window:N", scale=alt.Scale(domain=["this month", "next 3 months", "other"],
                                                            range=["#5f6368", "#e37400", "#c5cae9"])),
                tooltip=["month", "index", "window"])
            st.altair_chart(chart, use_container_width=True)
        except Exception:
            theme.chart("bar", df.set_index("month")["index"], "Month", "Seasonal price index (1.0 = average month)")
    if rep["lens_notes"] and any(rep["lens_notes"].values()):
        with st.expander("How your region, business, customers and situation shape the advice"):
            names = {"region": "Region", "business_type": "Business", "customer": "Customers", "your_situation": "Your situation"}
            for k, v in rep["lens_notes"].items():
                if v:
                    st.markdown(f"**{names.get(k, k.replace('_', ' ').title())}:** {v}")
    c = rep["cost"]
    st.info(f"This run cost ${c['total_usd']:.4f}: {c['model_calls']} AI calls, {c['paid_calls']} paid, "
            f"{c['model_calls'] - c['paid_calls']} served from saved answers.")
    st.caption(rep["fictional_notice"])
    with st.expander("Raw output of every step"):
        for e in res["events"]:
            st.markdown(f"**{STEP_TITLES[e['step']]}** (attempt {e['attempt']}, {e['status']})")
            st.json(e["detail"], expanded=False)


PAGES = ["Introduction", "Ask a question", "Real NOAA data", "Scenario demo (fictional)", "Data sources"]


def main() -> None:
    st.set_page_config(page_title="FishMarket AI", page_icon="🐟", layout="wide")
    st.markdown(theme.CSS + theme.brand_html((ROOT / "app" / "fishmarket_logo.svg").read_bytes()), unsafe_allow_html=True)
    page = st.sidebar.radio("Page", PAGES, key="page")
    if page == "Introduction":
        return extra_pages.intro()
    if page == "Ask a question":
        return extra_pages.ask_page()
    if page == "Real NOAA data":
        return extra_pages.real_page()
    if page == "Data sources":
        return extra_pages.sources_page()
    demo_page()


def demo_page() -> None:
    init_state()
    st.warning(BANNER)
    st.caption("Scenario demo: checked market insights for fishers, farms, processors and seafood buyers.")
    mode, mix = sidebar()
    profile = profile_form()
    if st.button("Run analysis", type="primary"):
        cases = active_cases()
        overrides = overrides_from_manifest(DEFAULT, cases) if cases else None
        slots = {s: st.empty() for s in STEPS}
        attempts: dict[str, dict] = {s: {} for s in STEPS}
        for s in STEPS:
            slots[s].markdown(card_html(s, {}), unsafe_allow_html=True)

        def on_event(ev: dict) -> None:
            s = ev["step"]
            if ev["status"] == "pending":
                return
            attempts[s][ev["attempt"]] = ev
            slots[s].markdown(card_html(s, attempts[s]), unsafe_allow_html=True)

        try:
            st.session_state["result"] = run(profile, overrides, on_event=on_event, llm=make_llm(mode, overrides), mix=mix)
        except ProfileError as e:
            st.session_state["result"] = None
            st.error("Please fix the profile: " + " ".join(e.problems))
        except LLMError as e:
            st.session_state["result"] = None
            st.error(f"The AI service could not be used: {e}")
    if st.session_state.get("result"):
        st.divider()
        show_result(st.session_state["result"])


main()
