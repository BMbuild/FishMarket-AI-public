"""Trust rating: a pure function. Confidence in the report comes only from here."""
from __future__ import annotations

QUALITY_FLAGS = {"unit_mismatch", "outlier", "duplicates", "missing_values", "date_range", "aging_data", "schema"}


def compute_trust(flags: set[str], usable_tiers: list[str]) -> dict:
    """First matching rule wins. `flags` are the series-level flags plus flags on usable sources.
    `usable_tiers` lists the trust tier of every usable source."""
    flags = set(flags)
    tiers = set(usable_tiers)
    reasons: list[str] = []
    if "generated_series" in flags:
        reasons.append("The fictional dataset has no series for this species and region, so Python generated one for this scenario.")
    if "fallback_sample_data" in flags:
        reasons.append("No approved source could be verified, so labelled sample data was used.")
    if "source_disagreement" in flags:
        reasons.append("Two sources disagree on recent prices.")
    if (not tiers or tiers <= {"C", "D"}) and "generated_series" not in flags:
        reasons.append("Only lower-trust sources (trade press or sample data) were usable.")
    if reasons:
        return {"rating": "low", "reasons": reasons}

    if "single_source" in flags:
        reasons.append("Only one approved source covers this market, so it could not be cross-checked.")
    q = sorted(flags & QUALITY_FLAGS)
    if q:
        reasons.append("Some data problems were found and handled: " + ", ".join(x.replace("_", " ") for x in q) + ".")
    if "stale_data" in flags:
        reasons.append("A source was left out because it was out of date.")
    if "source_rejected" in flags:
        reasons.append("A selected source was left out because its file could not be read correctly.")
    if "not_cross_checked" in flags:
        reasons.append("Some sources share too few recent months to be compared.")
    if reasons:
        return {"rating": "medium", "reasons": reasons}

    return {"rating": "high",
            "reasons": ["Several approved sources were checked and agree.", "No data problems were found."]}
