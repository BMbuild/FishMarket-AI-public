"""Real-world context for the fictional scenario demo.

The scenario's prices, markets and costs are fictional. This module looks up what the real databases say about the same
species and region (NOAA U.S. landings and dockside prices, the sourced mini-wiki, OECD farmed production) so that:
  * the report can show it in its own clearly labelled "Real U.S. data" panel, with sources, and
  * the analyst and summary agents get it as WORDS ONLY background (numbers stripped), because their grounding checks
    require every number to come from the fictional statistics table. Real and fictional numbers are never combined.
Species are mapped through data_real/crosswalk/scenario_species.csv (explicit, never guessed)."""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from . import live, real_data, wiki

ROOT = Path(__file__).resolve().parents[2]
MAP_PATH = ROOT / "data_real" / "crosswalk" / "scenario_species.csv"
REGION_PATH = ROOT / "data_real" / "crosswalk" / "scenario_regions.csv"
LABEL = "Real U.S. data"


@lru_cache(maxsize=1)
def mapping() -> dict:
    with open(MAP_PATH, newline="", encoding="utf-8") as f:
        return {r["scenario_species"]: r for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def regions() -> dict:
    """Scenario region -> NOAA region, from data_real/crosswalk/scenario_regions.csv."""
    with open(REGION_PATH, newline="", encoding="utf-8") as f:
        return {r["scenario_region"]: r["noaa_region"] for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def _noaa():
    return real_data.load()


def noaa_names(species: str, region: str) -> list[str]:
    row = mapping().get(species)
    if row is None:
        # a species picked or typed outside the hand-made list: use its own name if NOAA has it (scenario_noaa_species.csv)
        from .scenario_species import noaa_table
        nt = noaa_table()
        return [species] if (nt["species"].str.lower() == species.lower()).any() else []
    if not row["noaa_species"]:
        return []
    out = []
    for part in row["noaa_species"].split(";"):
        name, _, reg = part.partition("@")
        if not reg or reg == region:
            out.append(name.strip())
    return out


def words_only(text: str) -> str:
    """For the agents: keep the meaning without numbers. Sentences that are mostly numbers (dates, quotas) are dropped;
    in the rest, numbers and the brackets or units around them are removed."""
    keep = []
    for sent in re.split(r"(?<=[.;])\s+", text):
        nums = re.findall(r"\d[\d,.]*", sent)
        if len(nums) >= 2:
            continue
        t = re.sub(r"\(([^()]*\d[^()]*)\)", "", sent)
        t = re.sub(r"\$?\d[\d,]*(\.\d+)?\s*(%|percent|million|billion|lb|pounds|tonnes|metric tons|inches|years?)?", "", t)
        t = re.sub(r"\s+([,.;])", r"\1", re.sub(r"\s{2,}", " ", t)).strip(" ,")
        if len(t.split()) >= 4:
            keep.append(t)
    return " ".join(keep).strip()


@lru_cache(maxsize=256)
def build(species: tuple, region: str) -> tuple:
    """Context items for each scenario species: {id, species, text (with numbers, for display), agent_text, source}."""
    items, n = [], 0
    noaa = None
    nreg = regions().get(region)
    for sp in species:
        row = mapping().get(sp, {})
        names = noaa_names(sp, region)
        if names:
            noaa = noaa or _noaa()
            for nm in names:
                for reg in ([nreg] if nreg else []) + [None]:
                    a = real_data.analyse(noaa.df, nm, reg)
                    if a.get("ok"):
                        where = f"in {reg}" if reg else "nationally"
                        trend = a.get("trend_direction") or "no clear trend"
                        n += 1
                        items.append({"id": f"RW{n}", "species": sp, "source": "NOAA Fisheries landings (FOSS)",
                                      "text": f"{nm} {where}: real U.S. dockside price ${a['latest_price']:,.2f} per lb in {a['last_year']}; "
                                              f"5-year price trend {trend}.",
                                      "agent_text": f"{LABEL}: the real U.S. dockside price of {nm} {where} has a five-year trend that is {trend}."})
                        break
            hits = []
            for nm in names:
                hits += [e for sc, e in wiki.search(f"{nm} stock status rules", [nm], k=2) if e.type == "stock" and nm.lower() in e.species]
            for e in {e.id: e for e in hits}.values():
                n += 1
                items.append({"id": f"RW{n}", "species": sp, "source": f"Mini-wiki: {e.title} ({' '.join(e.sources)}, read {e.retrieved})",
                              "text": e.text, "agent_text": f"{LABEL} ({e.title}): {words_only(e.text)}"})
        if row.get("oecd_scientific") and (live.LOCAL_OECD.exists() or live.LOCAL_OECD_CLEAN.exists()):
            try:
                a = live.aquaculture(row["oecd_scientific"], "USA")
            except live.LiveError:
                a = {"match": "none"}
            if a.get("match") != "none" and a.get("series"):
                ser = a["series"].get("T") or next(iter(a["series"].values()))
                last = max(ser)
                n += 1
                items.append({"id": f"RW{n}", "species": sp, "source": "OECD Data Explorer, aquaculture production",
                              "text": f"OECD: U.S. farmed production of {a['species_label']} was {ser[last]:,.0f} tonnes in {last}.",
                              "agent_text": f"{LABEL}: OECD reports U.S. farmed production of {a['species_label'].split(' [')[0]}."})
        if row.get("note"):
            n += 1
            items.append({"id": f"RW{n}", "species": sp, "source": "FishMarket species mapping", "text": f"Note on {sp}: {row['note']}.",
                          "agent_text": f"Note on {sp}: {row['note']}."})
    return tuple(items)


# ---- the user's own question, from the scenario text box --------------------------------------------
QUESTION = re.compile(r"[^.!?\n]{8,300}\?")


def note_question(note: str) -> str:
    """The first real question in the user's note ("... ?"), or "". Only the question goes to the QA engine."""
    m = QUESTION.search(note or "")
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else ""


@lru_cache(maxsize=1)
def qa_context():
    from .qa.context import Context
    return Context.load(real_only=True, live=False)


def answer_question(question: str, species: tuple, region: str, llm=None, web: bool = False, cfg=None, mix: str = "dev", run_ctx=None) -> dict:
    """Answers the user's question with the real-data QA engine (real-only, offline template, nothing logged to disk).
    If it can't and web research is ticked, the web researcher tries (quotes only). Returns a display dict plus
    `agent_text`, a words-only version for the scenario agents."""
    from .config import DEFAULT
    from .qa import answer as qa
    cfg = cfg or DEFAULT
    nreg = regions().get(region)
    hint = next((n for sp in species for n in noaa_names(sp, nreg)), None)
    ctx = qa_context()
    r = qa._ask(question, ctx, None, None, nreg, True, mix, cfg, False)      # _ask, not ask: the note is never written to the misses log
    if hint and r.get("verdict") in ("cannot", "clarify") and getattr(r.get("plan"), "scope", "") != "non_us":
        r2 = qa._ask(question, ctx, None, hint, nreg, True, mix, cfg, False)
        if r2.get("verdict") in ("answered", "partly"):
            r = r2
    web_tried = False
    if web and llm is not None and hasattr(llm, "search_call") and qa.web_allowed(r):
        web_tried = True
        w = qa.web_answer(question, llm, cfg, mix, summarise=False, local=r, run_ctx=run_ctx)
        if w is not None:
            r = w
    claims = [c["text"] for c in r.get("claims", [])]
    agent_text = words_only(" ".join(claims)) if r.get("verdict") in ("answered", "partly") else ""
    return {"question": question, "verdict": r.get("verdict"), "answer_md": r.get("answer_md", ""), "origins": r.get("origins", []),
            "confidence": r.get("confidence"), "citations": r.get("citations", []), "web_tried": web_tried,
            "web_searches": (r.get("web") or {}).get("searches", 0), "cost_usd": r.get("cost_usd", 0.0),
            "agent_text": (f"The user asked a question; checked {'web quotes' if r.get('entry_id') == 'web_research' else 'real data'} say: {agent_text}" if agent_text else "")}
