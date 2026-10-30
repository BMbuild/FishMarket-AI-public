"""Step 8: assemble the final report. Caveats are fixed sentences added by Python."""
from __future__ import annotations

from .analytics import MONTHS
from .templates import caveats_for

FICTIONAL_LINE = "Fictional data, not real market prices."


def provenance(gate, registry, species: str = "") -> list[dict]:
    rows = []
    for sid, r in gate.sources.items():
        if not r.covers:
            continue
        if r.usable:
            status = "primary" if sid == gate.primary_id else "used"
        else:
            status = "excluded: " + (r.excluded_reason or "unusable")
        rows.append({"source_id": sid, "name": str(registry.loc[sid, "name"]), "tier": r.tier, "species": species,
                     "last_updated": r.last_updated, "rows_used": r.rows_kept if r.usable else 0,
                     "rows_dropped": r.rows_dropped, "flags": dict(r.flags), "status": status})
    return rows


def cost_block(tr, ctx) -> dict:
    per_step = {}
    for e in tr.events:
        if e["cost_usd"] or e["tokens_in"]:
            s = per_step.setdefault(e["step"], {"cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0})
            s["cost_usd"] += e["cost_usd"]; s["tokens_in"] += e["tokens_in"]; s["tokens_out"] += e["tokens_out"]
    return {"total_usd": tr.total_cost(), "model_calls": ctx.calls, "paid_calls": ctx.paid_calls, "per_step": per_step}


def _num(x):
    return None if x is None else float(x)


def _tables(res) -> dict:
    """Numbers for the report tables (the same Python results the statistics came from)."""
    t = {}
    tb = res.tables
    if "markets" in tb:
        m = tb["markets"]
        t["markets"] = {"ranking": [{k: (_num(v) if isinstance(v, (int, float)) else v) for k, v in r.items()} for r in m["ranking"]],
                        "excluded": [{k: (_num(v) if isinstance(v, (int, float)) else v) for k, v in r.items()} for r in m["excluded"]]}
    if "buyers" in tb:
        b = tb["buyers"]
        t["buyers"] = {"ranking": b["ranking"], "excluded": b["excluded"], "grade_used": b["grade_used"],
                       "grade_verified": b["grade_verified"], "used_segment_fit": b["used_segment_fit"]}
    if "best_months" in tb:
        t["best_months"] = {"top": [{"month": m, "score": _num(s)} for m, s in tb["best_months"]["top"]],
                            "open": tb["best_months"]["open"]}
    if "hold" in tb:
        t["hold"] = {k: (_num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in tb["hold"].items()}
    if "costs" in tb:
        c = tb["costs"]
        t["costs"] = {"per_type": {k: _num(v) for k, v in c["per_type"].items()}, "incomplete": c["incomplete"],
                      "top_type": c["top_type"], "squeeze": c["squeeze"]}
    return t


def build_report(brief, as_of, analysis, summary_md, trust, flags, gates, registry, stats, results, tr, ctx,
                 cautious, decision, op_row, clean_note, scan, note_info) -> dict:
    now = as_of.month - 1
    first = results[0]
    prov = []
    for r in results:
        prov += provenance(gates[r.species], registry, r.species)
    return {
        "fictional_notice": FICTIONAL_LINE,
        "series": brief.series,
        "question_type": brief.profile.question_type,
        "operation": op_row["label"],
        "as_of": str(as_of.date()),
        "direction": analysis.direction,
        "directions_by_series": decision["by_series"],
        "timing_window": analysis.timing_window,
        "headline": analysis.headline,
        "summary_md": summary_md,
        "confidence": trust,
        "caveats": caveats_for(flags, note_info),
        "provenance": prov,
        "claims": [c.model_dump() for c in analysis.claims],
        "actions": [a.model_dump() for a in analysis.actions],
        "lens_notes": analysis.lens_notes.model_dump(),
        "driver_tags": analysis.driver_tags,
        "cautious_answer": cautious,
        "species": [{"species": r.species, "series": r.series, "channel": r.channel, "source_id": r.source_id,
                     "quality": {k: v for k, v in r.quality.items() if k != "injection_phrases"},
                     "tables": _tables(r)} for r in results],
        "heard": ({"text": clean_note["text"], "truncated": clean_note["truncated"],
                   "flags": scan["flags"], "out_of_scope": scan["out_of_scope"], "conflicts": scan["conflicts"]}
                  if clean_note["text"] else None),
        "charts": {"history": first.history, "seasonal_index": first.seasonal_index, "months": MONTHS,
                   "now_index": now, "next3_indexes": [(now + k) % 12 for k in (1, 2, 3)]},
        "cost": None,
    }


def normalize_result(result: dict) -> dict:
    """Drop run ids and timestamps so two runs can be compared (replay snapshots)."""
    import json
    r = json.loads(json.dumps(result, default=str))
    for k in ("run_id", "saved_to", "paid_calls"):
        r.pop(k, None)
    (r.get("report") or {}).pop("cost", None)           # replay is free by design; money is not compared
    for e in r.get("events", []):
        for k in ("run_id", "started_at", "ended_at", "cost_usd", "cache", "tokens_in", "tokens_out"):
            e.pop(k, None)
    return r
