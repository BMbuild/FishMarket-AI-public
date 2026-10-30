"""Deterministic text: template claims, cautious answer, template summary, fixed caveat sentences."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from .config import Config, DEFAULT
from .grounding import contradictions, expected_direction, expected_tags, numerals_in, round_half_up
from .schemas import Action, AnalysisOutput, Claim, LensNotes, NumberRef, StatRow

CAVEATS = {
    "single_source": "Only one approved source covers this market, so the figures could not be cross-checked.",
    "source_disagreement": "Two sources disagree on recent prices, so treat this recommendation with extra care.",
    "stale_data": "A source or market was left out because it has not been updated recently enough.",
    "aging_data": "A source is getting old and was used with reduced confidence.",
    "unit_mismatch": "Some rows were reported in kilograms or ounces and were converted to pounds.",
    "outlier": "One or more prices looked wrong and were removed.",
    "duplicates": "Duplicate rows were removed.",
    "missing_values": "Some rows had missing values and were skipped, not estimated.",
    "date_range": "Rows dated after today were removed.",
    "fallback_sample_data": "No approved source could be verified, so labelled sample data was used.",
    "cautious_answer": "The AI analyst's explanation could not be verified, so only computed statistics and the rule-based direction are shown.",
    "template_summary": "The written summary was generated from a fixed template.",
    "schema": "Some rows had invalid values and were dropped.",
    "channel_fallback": "No prices exist for your sales channel in this market, so first-sale prices were used.",
    "no_storage_info": "No storage was given, so the cost of holding was not calculated.",
    "shelf_life_exceeded": "Your product would not keep long enough to reach the best month in that form.",
    "grade_assumed": "No verified quality grade was available, so the lowest grade was assumed.",
    "quality_unverified": "Quality records for this product are unverified. A qualified inspector must verify quality before you rely on it.",
    "quality_conflicted": "Inspectors disagree about this product's quality. Please have it verified manually before relying on it.",
    "currency_mismatch": "Some market postings were in Canadian dollars and were converted to US dollars.",
    "cost_data_incomplete": "Some input-cost data was missing, so that cost was not estimated.",
    "margin_squeeze": "Your input costs are rising faster than prices, so your margin is under pressure.",
    "untrusted_text_ignored": "Some text in your note or in a data record looked like an instruction and was ignored.",
    "note_out_of_scope": "Part of your note asked for something this tool cannot answer.",
    "profile_conflict": "Your note mentions something different from the form. We used the form.",
    "source_rejected": "A selected source was left out because its file could not be read correctly.",
    "not_cross_checked": "Two sources share too few recent months to be compared, so the figures could not be fully cross-checked.",
}
CAVEAT_ORDER = ["fallback_sample_data", "source_disagreement", "stale_data", "source_rejected", "single_source",
                "not_cross_checked", "channel_fallback",
                "unit_mismatch", "currency_mismatch", "outlier", "duplicates", "missing_values", "date_range", "schema",
                "aging_data", "quality_conflicted", "quality_unverified", "grade_assumed", "cost_data_incomplete",
                "margin_squeeze", "no_storage_info", "shelf_life_exceeded", "untrusted_text_ignored",
                "cautious_answer", "template_summary"]


def caveats_for(flags, note: dict | None = None) -> list[str]:
    out = [CAVEATS[f] for f in CAVEAT_ORDER if f in flags]
    note = note or {}
    if "species_skipped" in flags:
        out += [f"{sp} could not be checked against enough verified data, so it has no answer here."
                for sp in note.get("skipped_species") or ["One of the products you chose"]]
    if "note_out_of_scope" in flags:
        out.append("Part of your note asked for something this tool cannot answer"
                   + (": " + ", ".join(note["out_of_scope"]) if note.get("out_of_scope") else "") + ".")
    if "profile_conflict" in flags:
        out.append("Your note mentions " + (", ".join(note["conflicts"]) if note.get("conflicts") else "something different")
                   + ", but the form says something else. We used the form.")
    out += list(note.get("extra_caveats") or [])
    return out


def _s(stats, kind) -> Optional[StatRow]:
    return next((s for s in stats if s.kind == kind), None)


def _fmt(value: float, places: int) -> tuple[float, str]:
    d = round_half_up(value, places)
    signed = -float(d) if value < 0 else float(d)
    return signed, format(d, "f")


def _series_names(stats: list[StatRow]) -> list[str]:
    return list(dict.fromkeys(s.series for s in stats))


def timing_window(direction: str, stats: list[StatRow]) -> str:
    if direction == "hold":
        b = _s(stats, "seasonal_index_best_next3")
        return f"through {b.month}" if b and b.month else "over the next three months"
    if direction in ("sell_now", "buy_now"):
        return "now"
    if direction == "wait":
        return "over the next three months"
    return "not available"


def _claims_for_series(stats: list[StatRow], qtype: str, claims: list[Claim], who: str = "") -> None:
    pre = f"{who}: " if who else ""

    def add(text, stat_id, number=None):
        claims.append(Claim(id=f"C{len(claims) + 1}", text=pre + text, stat_ids=[stat_id],
                            numbers=[NumberRef(value=number, stat_id=stat_id)] if number is not None else []))

    if qtype == "best_months":
        for s in [x for x in stats if x.kind == "best_month_score"]:
            n, t = _fmt(s.value, 2)
            add(f"{s.label} scores {t} on the price-and-supply score.", s.id, n)
    if qtype == "compare_markets":
        for s in [x for x in stats if x.kind == "market_net_price"][:2]:
            n, t = _fmt(s.value, 2)
            add(f"{s.label} nets ${t} per pound after fees and freight.", s.id, n)
        g = _s(stats, "net_price_gap_pct")
        if g:
            n, t = _fmt(g.value, 1)
            add(f"The best market beats the second best by {t}%.", g.id, n)
        for s in [x for x in stats if x.kind == "market_age_days"]:
            n, t = _fmt(s.value, 0)
            add(f"{s.label} was left out because it last posted {t} days ago.", s.id, n)
    if qtype == "best_buyer_type":
        for s in [x for x in stats if x.kind == "buyer_net_price"][:2]:
            n, t = _fmt(s.value, 2)
            add(f"{s.label} would net about ${t} per pound after fees and payment delay.", s.id, n)
        g = _s(stats, "net_price_gap_pct")
        if g:
            n, t = _fmt(g.value, 1)
            add(f"The best buyer type beats the second best by {t}%.", g.id, n)
    ranking = qtype in ("best_months", "compare_markets", "best_buyer_type")
    r = None if ranking else (_s(stats, "best_next3_vs_now_ratio") if qtype == "sell_or_hold" else _s(stats, "next3_mean_vs_now_ratio"))
    if r:
        n, t = _fmt(r.value, 2)
        if qtype == "sell_or_hold":
            add(f"The best of the next three months has a seasonal price index {t} times this month's.", r.id, n)
        else:
            add(f"On average the next three months have a seasonal price index {t} times this month's.", r.id, n)
    p = _s(stats, "seasonal_peak_month")
    if p and p.reliability == "strong" and qtype == "sell_or_hold" and not ranking:
        add(f"Prices in this market usually peak in {p.month}.", p.id)
    y = _s(stats, "yoy_price_change_pct")
    if y:
        n, t = _fmt(y.value, 1)
        word = "lower" if y.value < 0 else "higher"
        add(f"Over the last 12 months the average price was {t}% {word} than the 12 months before.", y.id, n)
    s = None if ranking else _s(stats, "supply_yoy_change_pct")
    if s:
        n, t = _fmt(s.value, 1)
        word = "lower" if s.value < 0 else "higher"
        add(f"Supply in the latest three months was {t}% {word} than the same months a year earlier.", s.id, n)
    h = _s(stats, "hold_net_gain_pct")
    if h:
        n, t = _fmt(h.value, 1)
        word = "loss" if h.value < 0 else "gain"
        add(f"After storage cost and shrink, holding is a net {word} of about {t}%.", h.id, n)
    g = _s(stats, "margin_squeeze_gap_pts")
    if g and g.value >= 5:
        n, t = _fmt(g.value, 1)
        add(f"Your largest input cost ({g.label.replace('_', ' ')}) is rising {t} points faster than prices.", g.id, n)
    lp = _s(stats, "latest_price")
    if lp:
        n, t = _fmt(lp.value, 2)
        add(f"The latest price was ${t} per pound ({lp.month}).", lp.id, n)


_LENS = {
    "customer": {
        "premium": "Premium buyers care about quality and provenance more than volume.",
        "mainstream": "Mainstream buyers want reliable supply and consistent pricing.",
        "price_sensitive": "Price-sensitive buyers value steady volume and low cost, so a small gain from waiting may not pay.",
    },
}



def template_claims(stats: list[StatRow], qtype: str = "sell_or_hold") -> list[Claim]:
    claims: list[Claim] = []
    names = _series_names(stats)
    for ser in names:
        rows = [s for s in stats if s.series == ser]
        _claims_for_series(rows, qtype, claims, ser.split("|")[0] if len(names) > 1 else "")
    return claims[:6] if len(names) == 1 else claims[: 3 * len(names)] if len(claims) > 6 else claims


def recommendation_sentence(direction: str, qtype: str, species: str, window: str, stats: list[StatRow]) -> str:
    if direction == "per_species":
        return f"Each product has its own answer below ({species})."
    if qtype == "sell_or_hold":
        if direction == "hold":
            return f"Hold your {species} and plan to sell later" + (f", {window}" if window.strip() else "") + "."
        if direction == "sell_now":
            return f"Sell your {species} now."
    if qtype == "buy_now_or_wait":
        if direction == "buy_now":
            return f"Buy your {species} now."
        if direction == "wait":
            return f"Wait before buying your {species}."
        if direction == "no_clear_signal":
            return f"The seasonal pattern gives no clear signal on when to buy {species}."
    if direction == "ranking":
        if qtype == "best_months":
            m = [s.label for s in stats if s.kind == "best_month_score"]
            return f"The best months for {species} are " + ", ".join(m) + "."
        if qtype == "compare_markets":
            m = next((s.label for s in stats if s.kind == "market_net_price"), "")
            return f"{m} pays the most for {species} after fees and freight."
        if qtype == "best_buyer_type":
            m = next((s.label for s in stats if s.kind == "buyer_net_price"), "")
            return f"{m} is the best type of buyer for your {species}."
    return f"There is not enough data to answer this question for your {species}."


_ACTIONS = {
    "hold": ["If you can store your product safely, plan to sell more of it later in the window rather than all now.",
             "Sell in steps as prices improve instead of all at once."],
    "sell_now": ["Plan to sell at current prices; waiting is not expected to pay off.",
                 "Check again next month before making new commitments."],
    "buy_now": ["Plan your purchases now rather than later in the window.", "Check again next month before committing more."],
    "wait": ["Hold off on large purchases for now.", "Check again next month before committing."],
    "no_clear_signal": ["Buy as you normally would; timing is not expected to matter much.", "Check again next month."],
    "ranking": ["Use the ranking as a starting point and confirm the details with the market or buyer before committing.",
                "Check again next month before making new commitments."],
    "per_species": ["Read each product's result separately; do not blend them.", "Check again next month."],
    "insufficient_data": ["There is not enough price history to give a recommendation.", "Check again when more data is available."],
}


def template_analysis(stats: list[StatRow], profile=None, cfg: Config = DEFAULT, with_lens: bool = False,
                      qtype: str = "sell_or_hold", op_label: str = "") -> AnalysisOutput:
    direction = expected_direction(stats, cfg, qtype)
    claims = template_claims(stats, qtype)
    cid = claims[0].id if claims else ""
    refs = [cid] if cid else []
    window = timing_window(direction, stats)
    species = ", ".join(s.split("|")[0] for s in _series_names(stats))
    headline = recommendation_sentence(direction, qtype, species, window, stats)
    if len(headline.split()) > 25:
        headline = " ".join(headline.split()[:25])
    acts = _ACTIONS.get(direction, _ACTIONS["insufficient_data"])
    lens = LensNotes()
    if with_lens and profile is not None:
        lens = LensNotes(region=f"These figures are for {profile.region} only.",
                         business_type=(f"This is framed for a {op_label.lower()}." if op_label else ""),
                         customer=_LENS["customer"].get(profile.customer_segment, ""),
                         your_situation=_situation_line(profile))
    tags = sorted(expected_tags(stats, direction, cfg)) if qtype == "sell_or_hold" and direction != "per_species" else []
    return AnalysisOutput(direction=direction, timing_window=window, headline=headline, claims=claims,
                          driver_tags=tags, actions=[Action(text=x, claim_ids=refs) for x in acts], lens_notes=lens)


def _situation_line(profile) -> str:
    parts = []
    if getattr(profile, "goal", ""):
        parts.append(f"your goal ({profile.goal})")
    if getattr(profile, "constraints", None):
        parts.append("your constraints (" + ", ".join(profile.constraints) + ")")
    if not parts:
        return ""
    return "Weigh this against " + " and ".join(parts) + "."


def template_summary(direction: str, window: str, species: str, claims: list[Claim], actions: list[Action],
                     rating: str, reasons: list[str], caveats: list[str], qtype: str = "sell_or_hold",
                     stats: list[StatRow] | None = None) -> str:
    rec = recommendation_sentence(direction, qtype, species, window, stats or [])
    why = "\n".join(f"- {c.text}" for c in claims[:3]) or "- No verified statistics were available."
    todo = "\n".join(f"- {a.text}" for a in actions[:3])
    sure = f"Confidence: {rating}. " + " ".join(reasons + [c for c in caveats if not any(c.startswith(r.rstrip(".")) for r in reasons)])
    return f"## Recommendation\n{rec}\n\n## Why\n{why}\n\n## What to do\n{todo}\n\n## How sure we are\n{sure}\n"


HEADINGS = ["## Recommendation", "## Why", "## What to do", "## How sure we are"]


def check_summary(md: str, rating: str, claims: list[Claim], forbidden_phrases: tuple = (),
                  recommendation: str | None = None, direction: str | None = None) -> list[str]:
    """`recommendation` is Python's sentence; the summary must state it word for word and nothing against it."""
    v = []
    for ph in forbidden_phrases:
        if ph and ph in md.lower():
            v.append(f"the summary repeats instruction-like text ({ph!r})")
    found = re.findall(r"^##\s.*$", md, re.M)
    if [h.strip() for h in found] != HEADINGS:
        v.append(f"headings must be exactly {HEADINGS}; found {found}")
    if recommendation is not None:
        rec = re.search(r"## Recommendation\s*\n(.*?)(?=\n##|\Z)", md, re.S)
        said = " ".join(rec.group(1).split()) if rec else ""
        if said != " ".join(recommendation.split()):
            v.append(f"the recommendation must be exactly {recommendation!r}; found {said!r}")
    if direction is not None:
        for ph in contradictions(md, direction):
            v.append(f"the summary says {ph!r}, which contradicts the direction {direction}")
    sec = re.search(r"## How sure we are\s*\n(.*)", md, re.S)
    # Capitalisation is not a different rating ("Confidence: High." is fine); any other wording is rejected.
    if not sec or not sec.group(1).strip().lower().startswith(f"confidence: {rating.lower()}."):
        v.append(f"the last section must start with 'Confidence: {rating}.'")
    allowed = set()
    for c in claims:
        allowed |= set(numerals_in(c.text))
        allowed |= {abs(Decimal(repr(float(n.value)))) for n in c.numbers}
    for n in numerals_in(md):
        if n not in allowed:
            v.append(f"the number {n} does not appear in the verified claims")
    if len(md.split()) > 300:
        v.append("more than 300 words")
    return v
