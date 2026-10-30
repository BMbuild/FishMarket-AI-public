"""Introduction, real-data and data-source pages for the Streamlit app."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from fishmarket import contracts, evidence, gbif, real_data, real_summary, species_info, validators
from fishmarket.qa import catalogue
from fishmarket.qa.answer import ask as qa_ask
from fishmarket.qa.context import Context
from fishmarket.sources import SOURCES, STATUS_TEXT

import theme


def intro() -> None:
    st.markdown(f"""<div class='fm-hero'><h1>FishMarket AI</h1>
<p>Checked seafood price information for fishers, farms, processors and buyers, explained in plain language.</p></div>
{theme.animals('whale', 'fish', 'crab', 'jelly', 'turtle', 'octopus')}""", unsafe_allow_html=True)
    cols = st.columns(3)
    blocks = [
        ("What it does", "Looks at seafood prices and landings, runs every row through a validation gate, and tells you what the numbers say: "
                         "price trend, ups and downs, which region pays more, and in the demo whether to sell or hold."),
        ("How it works", "A fixed 8-step pipeline. Python checks the data and does every calculation. Three AI agents "
                         "(retrieval planner, analyst, summary writer) only choose what to look at and explain results. A grounding check "
                         "rejects any sentence whose numbers do not match the calculation."),
        ("What it will not do", "It does not predict prices, give financial advice, or invent numbers. If data is missing, stale or "
                                "conflicting it says so instead of guessing. Free-text notes are treated as untrusted and never change a calculation."),
    ]
    for c, (t, b) in zip(cols, blocks):
        c.markdown(f"<div class='fm-card'><b>{t}</b><br>{b}</div>", unsafe_allow_html=True)
    st.markdown("<div class='fm-card'><b>Two modes</b><br>"
                "<b>Real NOAA data</b>: real annual dockside prices and landings from NOAA Fisheries (1950-2024). Annual only, so it shows long-run trends, not monthly timing.<br>"
                "<b>Scenario demo</b>: a fully fictional monthly dataset with planted data problems, used to show the checks, the AI agents and the sell-or-hold style questions. "
                "It is always labelled fictional.</div>", unsafe_allow_html=True)
    st.markdown("<div class='fm-note'>Start with <b>Ask a question</b> or <b>Real NOAA data</b> in the left menu. Information only, not financial advice.</div>", unsafe_allow_html=True)


@st.cache_data(show_spinner="Reading NOAA landings...")
def _load():
    L = real_data.load()
    return L, real_data.provenance(L), real_data.species_list(L.df)


def real_page() -> None:
    st.markdown("<div class='fm-hero'><h1>Real NOAA data</h1></div>", unsafe_allow_html=True)
    st.success("Real data: NOAA Fisheries landings (annual, dockside value). Recreational catch is NOAA survey estimates.")
    if not real_data.DEFAULT_CSV.exists():
        st.error(f"{real_data.DEFAULT_CSV.name} not found. Run scripts/extract_noaa_full.py first.")
        return
    L, prov, species = _load()
    view = st.radio("View", ["Species report", "Browse the market"], key="real_view", horizontal=True)
    if view == "Browse the market":
        return browse(L)
    species_report(L, prov, species)


def species_report(L, prov, species) -> None:
    df = L.df
    c1, c2, c3 = st.columns([2, 2, 1])
    sp = c1.selectbox("Species", species, index=species.index("American lobster") if "American lobster" in species else 0)
    regs = ["All regions"] + real_data.regions_for(df, sp)
    rg = c2.selectbox("Region", regs)
    unit = c3.radio("Unit", ["lb", "kg"], horizontal=True)
    gate = validators.gate_series(L, sp, rg)
    gate_panel(gate)
    try:
        contracts.ensure_confirmable([gate])
    except contracts.FlaggedRecordError:
        st.error("Analysis stopped by the validation gate: " + str(gate.flag_reason) + " " + str(gate.required_action))
        return
    a = real_data.analyse(df, sp, rg)
    if not a["ok"]:
        st.warning(a["reason"])
        return
    f = real_data.to_kg if unit == "kg" else (lambda x: x)
    u = f"USD/{unit}"
    st.markdown(f"<div class='fm-card'><b>{a['read']}</b></div>", unsafe_allow_html=True)
    m = st.columns(4)
    m[0].metric(f"{a['last_year']} price ({u})", f"{f(a['latest_price']):.2f}", None if a["yoy_price_pct"] is None else f"{a['yoy_price_pct']:+.1f}% YoY")
    m[1].metric("5-yr avg price", "n/a" if "recent_avg_price" not in a else f"{f(a['recent_avg_price']):.2f}")
    m[2].metric("Year-to-year swings", a.get("volatility_label", "n/a"))
    m[3].metric(f"{a['last_year']} landings (million lb)", f"{a['latest_pounds'] / 1e6:,.1f}")
    for fl in real_data.interpretation_flags(a):
        st.info(fl)
    # price chart, nominal or inflation-adjusted
    trend = real_data.real_trend(df, sp, rg)
    s = real_data.series(df, sp, rg)
    s["price"] = s["price"].map(f)
    chart = s.set_index("year")[["price"]].rename(columns={"price": f"Price ({u}, as reported)"})
    if trend.get("ok"):
        rs = trend["real_series"].set_index("year")["real"].map(f)
        chart[f"Price ({u}, in {trend['base_year']} dollars)"] = rs
    st.caption("Dockside price over time. The second line removes inflation (BLS CPI-U).")
    theme.chart("line", chart, "Year", f"Dockside price ({u})")
    if trend.get("ok"):
        st.write(f"Since {trend['first_year']}: **{trend['nominal_cagr_pct']:.1f}% a year** as reported, "
                 f"**{trend['real_cagr_pct']:.1f}% a year** after inflation (inflation alone: {trend['inflation_cagr_pct']:.1f}%).")
    st.caption("Landings, million lb")
    theme.chart("bar", s.assign(m=s["pounds"] / 1e6).set_index("year")["m"], "Year", "Landings (million lb)")
    # states
    stt = real_data.state_table(L.states, sp, region=rg)
    conc = real_data.concentration(stt)
    if conc["ok"]:
        st.subheader(f"By state, {stt.attrs.get('year', a['last_year'])}")
        st.write(f"Landings are **{conc['label']}**: {conc['top_state']} supplies {conc['top_share_pct']:.1f}%, top 3 states {conc['top3_share_pct']:.1f}%.")
        t = stt.copy()
        t["price"] = t["price"].map(f).round(2)
        t["million lb"] = (t.pop("pounds") / 1e6).round(2)
        t["share_pct"] = t["share_pct"].round(1)
        st.dataframe(t.rename(columns={"price": u}), hide_index=True, use_container_width=True)
        pick = st.selectbox("Drill into a state", list(stt["state"]), key="real_state")
        ss = real_data.state_series(L.states, sp, pick)
        if len(ss):
            theme.chart("line", ss.assign(price=ss["price"].map(f)).set_index("year")["price"], "Year", f"Dockside price in {pick} ({u})")
    rec = real_data.rec_vs_commercial(L, sp, rg)
    if rec["ok"]:
        st.subheader("Recreational vs commercial")
        st.write(f"In {rec['year']}, anglers caught **{rec['rec_share_pct']:.1f}%** of the combined pounds ({rec['label']}). {rec['note']}")
        theme.chart("line", rec["table"].assign(**{"Recreational (million lb)": rec["table"]["rec_pounds"] / 1e6,
                                                   "Commercial (million lb)": rec["table"]["comm_pounds"] / 1e6}
                                                ).set_index("year")[["Recreational (million lb)", "Commercial (million lb)"]],
                    "Year", "Catch (million lb)")
    if rg == "All regions" and a.get("regions_latest_year"):
        st.subheader(f"Which region paid most in {a['last_year']}")
        t = pd.DataFrame(a["regions_latest_year"])
        t["price"] = t["price"].map(f).round(2)
        t["million lb"] = (t.pop("pounds") / 1e6).round(1)
        st.dataframe(t.rename(columns={"price": u}), hide_index=True, use_container_width=True)
    species_panel(df, sp)
    ev_text = evidence_panel(a)
    st.subheader("Plain-language summary")
    claims = real_summary.build_claims(a, trend, conc, rec)
    mode = st.selectbox("Summary writer", ["Offline template (free)", "AI (uses saved answers, then the API)"], key="real_sum_mode")
    llm = None
    if mode.startswith("AI"):
        from fishmarket.llm import LLM
        from fishmarket.config import DEFAULT
        try:
            llm = LLM(DEFAULT, mode="auto")
        except Exception as e:
            st.warning(f"AI not available ({type(e).__name__}); using the template.")
    out = real_summary.summarise(claims, llm, evidence_block=ev_text or None)
    st.markdown(out["markdown"])
    st.caption("Written by " + ("the AI, every number checked against the claims above." if out["source"] == "ai"
                                else "a template" + (f" ({out['reason']})" if out["reason"] else "") + "."))
    st.subheader("Caveats")
    for c in a["caveats"]:
        st.write("- " + c)
    quality_panel(L)
    with st.expander("Data provenance"):
        st.json(prov)


def gate_panel(h) -> None:
    st.markdown(f"<div class='fm-card'><b>Validation gate (collection to analysis)</b> &nbsp; {theme.pill(h.status)}<br>"
                f"{h.payload.get('valid_years', 0)} valid years. "
                + (f"{h.flag_reason} {h.required_action or ''}" if h.flag_reason else "No missing, zero or suspicious rows for this selection.")
                + "</div>", unsafe_allow_html=True)


def quality_panel(L) -> None:
    rep = L.notes["gate"]
    with st.expander("Whole-file data quality (what the gate did with all NOAA rows)"):
        bs = rep["by_status"]
        st.write(f"Of {rep['total_rows']:,} rows: **{bs.get('VALID', 0):,} valid**, {bs.get('EXCLUDED_BY_DESIGN', 0):,} not errors by design "
                 f"(recreational rows have no dollars; zero-fill placeholders mean nothing landed), **{bs.get('REJECTED', 0):,} rejected**, "
                 f"{bs.get('REVIEW', 0):,} held back for review. Pass rate on rows that should have values: **{rep['pass_rate_in_scope']:.1%}**.")
        st.dataframe(pd.DataFrame(sorted(rep["reason_counts"].items(), key=lambda kv: -kv[1]), columns=["reason", "rows"]),
                     hide_index=True, use_container_width=True)
        c = L.classified
        for label, status in (("Rejected rows (csv)", "REJECTED"), ("Rows held for review (csv)", "REVIEW")):
            st.download_button(label, c[c["status"] == status].to_csv(index=False).encode(), file_name=f"noaa_{status.lower()}.csv", mime="text/csv")


def species_panel(df, species: str) -> None:
    st.subheader("About this species (GBIF and FishBase)")
    sci = df.loc[df["species"] == species, "scientific"].dropna()
    sci = sci.iloc[0].strip() if len(sci) else ""
    if not sci or len(sci.split()) < 2:
        st.caption("NOAA gives no full scientific name for this group, so GBIF and FishBase are skipped.")
        return
    st.caption(f"Looked up by scientific name: {sci}. Background only; it never changes a price or number.")
    key = "species_info_" + sci
    if st.button("Look up species background", key="btn_" + key):
        with st.spinner("Contacting GBIF and FishBase..."):
            st.session_state[key] = species_info.lookup(sci)
    info = st.session_state.get(key)
    if not info:
        return
    g = info.get("gbif")
    if g and g.get("trusted"):
        st.write(f"**{g['scientific_name']}**, family {g.get('family')}, order {g.get('order')}. Common names: "
                 f"{', '.join(g.get('common_names', [])) or 'none listed'}. [GBIF page]({g['page']})")
        pts = g.get("points") or []
        if pts:
            st.caption(f"{len(pts)} recorded sightings in US waters and coasts (GBIF, of {g.get('occurrence_count_us', 0):,} total)")
            st.map(pd.DataFrame(pts, columns=["lat", "lon"]))
    elif g:
        st.warning(g.get("note", "GBIF match not trusted."))
    fb = info.get("fishbase") or {}
    if fb.get("found"):
        st.write("FishBase: " + ", ".join(f"{k} {v}" for k, v in fb["facts"].items()))
    elif fb.get("note"):
        st.caption("FishBase: " + fb["note"])
    for e in info.get("errors", []):
        st.warning("Could not reach a source: " + e)


def browse(L) -> None:
    df = L.df
    year = int(df["year"].max())
    st.subheader(f"Biggest species by value, {year}")
    by = st.radio("Rank by", ["dollars", "pounds"], key="browse_by", horizontal=True)
    t = real_data.top_species(df, year, by)
    t = t.assign(**{"million USD": (t["dollars"] / 1e6).round(1), "million lb": (t["pounds"] / 1e6).round(1), "USD/lb": t["price"].round(2)})
    st.dataframe(t[["species", "million USD", "million lb", "USD/lb"]], hide_index=True, use_container_width=True)
    m = real_data.movers(df, year)
    st.subheader(f"Biggest price moves vs {year - 1}")
    st.caption("Only species with at least $5 million landed value in both years.")
    for label, key in (("Price up", "up"), ("Price down", "down")):
        st.write(f"**{label}**")
        x = m[key]
        x = x.assign(**{"price change %": x["price_chg_pct"].round(1), "landings change %": x["pounds_chg_pct"].round(1),
                        "USD/lb now": x["price_now"].round(2)})
        st.dataframe(x[["species", "USD/lb now", "price change %", "landings change %"]], hide_index=True, use_container_width=True)


def evidence_panel(a: dict) -> str:
    st.subheader("Your evidence (optional)")
    st.caption(f"Attach up to {evidence.MAX_FILES} files (csv, txt, md, pdf, png, jpg; under 2 MB). They are labelled "
               f"'{evidence.TIER}', shown next to the NOAA numbers, and never change them. A CSV with a price column "
               "(and optional unit column, lb or kg) is compared with NOAA.")
    up = st.file_uploader("Attach evidence", accept_multiple_files=True, key="evidence_files",
                          type=["csv", "txt", "md", "pdf", "png", "jpg", "jpeg"])
    up = up if isinstance(up, list) else []
    if not up:
        return ""
    excerpts = []
    for ev in evidence.ingest_many([(f.name, f.getvalue()) for f in up]):
        with st.expander(f"{ev['name']}  ({ev['kind']})"):
            for p in ev.get("problems", []):
                st.warning(p)
            if "untrusted_text_ignored" in ev.get("flags", []):
                st.warning("This file contains text that looks like instructions to an AI. It is ignored.")
            if ev.get("note"):
                st.write(ev["note"])
            if ev.get("excerpt"):
                st.text(ev["excerpt"])
            cmp = evidence.compare_to_noaa(ev, a["latest_price"], a["last_year"])
            if cmp:
                (st.warning if cmp["differs_a_lot"] else st.info)(
                    f"Your median ${cmp['evidence_median_usd_lb']:.2f}/lb vs NOAA {cmp['noaa_year']} "
                    f"${cmp['noaa_price_usd_lb']:.2f}/lb ({cmp['gap_pct']:+.1f}%). {cmp['reading']}")
            st.caption(f"sha256 {ev.get('sha256', '')}  |  {ev['tier']}")
        if ev.get("excerpt") and not ev.get("flags"):
            excerpts.append(ev["excerpt"])
    return " | ".join(excerpts)[:600]


def sources_page() -> None:
    st.markdown("<div class='fm-hero'><h1>Data sources</h1></div>", unsafe_allow_html=True)
    lake_status()
    st.caption("What is wired in, what is not, and why. Nothing is marked verified unless it was actually reached.")
    for s in SOURCES:
        st.markdown(f"<div class='fm-card'><b>{s['name']}</b> &nbsp; <i>{STATUS_TEXT[s['status']]}</i><br>"
                    f"{s['gives']}<br><span class='fm-note'>{s['how']}<br>{s['url']}</span></div>", unsafe_allow_html=True)


def lake_status():
    """Show GBIF lake build status."""
    g = gbif.Gold()
    if g.available:
        status = f"GBIF lake built: {g.manifest.get('built_at', 'unknown')}"
        if g.manifest.get("is_test_fixture"):
            status += " (TEST FIXTURE - synthetic data)"
        st.info(status)
    else:
        st.warning("GBIF lake not built. Run `python -m fishmarket.lake build <download>`")


# ---------------------------------------------------------------- Ask a question
@st.cache_resource(show_spinner="Loading NOAA and GBIF data...")
def _qa_ctx(lake_stamp: str):
    return Context.load()


def ask_page() -> None:
    st.markdown("<div class='fm-hero'><h1>Ask a question</h1><p>Ask about seafood prices, landings, where a species is found, or when it is recorded. "
                "Every answer shows its data sources, whether the data is real or generated, and how confident to be.</p></div>", unsafe_allow_html=True)
    g = gbif.Gold()
    if not g.available:
        st.warning("GBIF data is not built yet, so only NOAA questions can be answered. Build it with `python -m fishmarket.lake build <download>`.")
        if st.button("Build the synthetic TEST FIXTURE lake (for trying the page; not real GBIF data)", key="build_fixture"):
            from fishmarket import lake as lk
            lk.main(["build", "--sample"])
            st.rerun()
    elif g.manifest.get("is_test_fixture"):
        st.warning("The GBIF data loaded here is a synthetic TEST FIXTURE, not real GBIF records. GBIF answers are capped at Low confidence.")
    ctx = _qa_ctx(str(g.manifest.get("built_at", "none")))
    cat = catalogue.load()
    st.caption("Covers U.S. markets only: NOAA U.S. landings and dockside prices. Other countries appear only for farmed production (OECD) and U.S. trade.")
    st.caption("Try one:")
    cols = st.columns(3)
    examples = [("price_history", "American lobster"), ("range_shift", "Atlantic cod"), ("seasonal_presence", "Bluefin tuna"),
                ("price_vs_inflation", "Haddock"), ("best_region_price", "Sea scallop"), ("monthly_timing", "Blue crab")]
    for i, (eid, sp) in enumerate(examples):
        q = cat[eid]["examples"][1 if "{species}" in cat[eid]["examples"][1] else 0].replace("{species}", sp).replace("{region}", "New England")
        if cols[i % 3].button(q, key=f"ex_{eid}"):
            st.session_state["ask_q"] = q
    q = st.text_input("Your question", key="ask_q")
    c1, c2, c3 = st.columns(3)
    sp = c1.selectbox("Species (optional)", [""] + ctx.species, key="ask_species")
    rg = c2.selectbox("Region (optional)", [""] + ctx.regions, key="ask_region")
    real_only = c3.checkbox("Real data only (no generated or fictional stand-ins)", key="ask_real_only")
    mode = st.selectbox("Writer", ["Offline template (free)", "AI planner and summary (saved answers first, then the API)"], key="ask_mode")
    web = st.checkbox("Search the web if the local data can't answer (up to 3 searches, about $0.03-0.06)", key="ask_web", value=False,
                      disabled=not mode.startswith("AI"),
                      help="Off by default. Needs the AI writer. A separate researcher searches official sites first (NOAA, FDA, USDA, "
                           "FAO, fishery councils, state agencies), then the open web if those have nothing. Only exact quotes with links "
                           "are kept, and every number shown must appear in a quote. Never used for questions the local data answers.")
    if st.button("Ask", type="primary", key="ask_go") and q:
        llm = None
        if mode.startswith("AI"):
            try:
                from fishmarket.llm import LLM
                from fishmarket.config import DEFAULT
                llm = LLM(DEFAULT, mode="auto")
            except Exception as e:
                st.warning(f"AI not available ({type(e).__name__}); using the offline template.")
        st.session_state["ask_result"] = qa_ask(q, ctx, llm=llm, species=sp or None, region=rg or None, real_only=real_only,
                                                web=bool(web and llm is not None))
    r = st.session_state.get("ask_result")
    if r:
        show_answer(r)


def show_answer(r: dict) -> None:
    label = {"answered": "ANSWERED", "partly": "PARTLY ANSWERED", "cannot": "CANNOT ANSWER WITH THIS DATA", "clarify": "NEED A DETAIL"}[r["verdict"]]
    cls = {"answered": "OK", "partly": "WARNING", "cannot": "FLAGGED", "clarify": "WARNING"}[r["verdict"]]
    pills = " ".join(theme.origin_pill(o) for o in r["origins"])
    conf = f" &nbsp; confidence <b>{r['confidence']}</b>" if r.get("confidence") else ""
    st.markdown(f"<div class='fm-card'>{theme.pill(cls).replace(cls, label)} &nbsp; {pills}{conf}</div>", unsafe_allow_html=True)
    st.markdown(r["answer_md"])
    d = r.get("data") or {}
    if "series" in d:
        s = d["series"]
        col = "price" if r["entry_id"] != "landings_trend" else "pounds"
        theme.chart("line", s.set_index("year")[[col]], "Year", "Dockside price (USD per lb)" if col == "price" else "Landings (lb)")
    if "decades" in d:
        theme.chart("line", d["decades"].set_index("decade")["lat"], "Decade", "Average latitude of records (degrees north)")
    if "hist" in d:
        theme.chart("bar", d["hist"], "Month (1 = January)", "Number of GBIF records")   # numeric, so months stay in calendar order
    if "points" in d and len(d["points"]):
        st.caption("Sample of recorded locations (not abundance)")
        st.map(d["points"].rename(columns={"lat": "lat", "lon": "lon"})[["lat", "lon"]])
    if r.get("confidence_reasons"):
        st.write("**Confidence:** " + " ".join(r["confidence_reasons"]))
    if r.get("unverified"):
        with st.expander("AI-written version (not verified)"):
            st.warning("Not verified: this AI wording failed an automatic check (" + r["unverified"]["problem"] + "), so it may add "
                       "judgments or numbers that are not in the data. The verified answer above is the one to rely on.")
            st.markdown(r["unverified"]["markdown"])
    if r.get("web"):
        w = r["web"]
        st.caption(f"Web research: {w['searches']} search(es); " + ", ".join(f"{p['scope']} sites: {p['facts']} quote(s)" for p in w["passes"])
                   + (f". {w['error']}" if w.get("error") else ""))
    if r.get("evidence"):
        with st.expander("Evidence: every claim, its dataset, query and rows"):
            st.dataframe(pd.DataFrame(r["evidence"]), hide_index=True, use_container_width=True)
    if r.get("caveats"):
        with st.expander("Caveats"):
            for c in r["caveats"]:
                st.write("- " + c)
    if r.get("citations"):
        with st.expander("Citations"):
            for c in r["citations"]:
                st.write("- " + c)
