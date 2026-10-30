"""Scores a pipeline result against a golden case. Lives in evals/ (never in src/) because it reads expectations."""
from __future__ import annotations

TOL = 0.011


def _stat(res, kind, label=None):
    return next((s for s in res["stats"] if s["kind"] == kind and (label is None or s["label"] == label)), None)


def check_case(case: dict, res: dict, model_inputs: list[str] | None = None) -> list[str]:
    """Returns a list of problems (empty means pass). Compares what Python computed with the expected block."""
    e, bad = case["expected"], []
    if res.get("status") != "ok":
        return [f"run failed: {res.get('message')}"]
    qt = e.get("question_type", "sell_or_hold")
    rep = res["report"]
    flags = set(res["flags"])
    if "expected_trust" in e and res["trust"]["rating"] != e["expected_trust"]:
        bad.append(f"trust {res['trust']['rating']} != {e['expected_trust']}")
    miss = set(e.get("required_gate_flags", [])) - flags
    if miss:
        bad.append(f"missing flags {sorted(miss)} (have {sorted(flags)})")
    if "direction" in e and res["analysis"]["direction"] != e["direction"]:
        bad.append(f"direction {res['analysis']['direction']} != {e['direction']}")
    if "cautious_answer" in flags or "template_summary" in flags:
        bad.append("fell back to a template")
    q = rep["species"][0]["quality"]["status"] if rep.get("species") else None
    if "quality_status" in e and q != e["quality_status"]:
        bad.append(f"quality status {q} != {e['quality_status']}")
    if qt in ("sell_or_hold", "buy_now_or_wait") and "per_species" not in e:
        key = "best_next3_vs_now_ratio" if qt == "sell_or_hold" else "next3_mean_vs_now_ratio"
        want = e.get("best_next3_vs_now_ratio") if qt == "sell_or_hold" else e.get("mean_next3_vs_now_ratio")
        s = _stat(res, key)
        if want is not None and (s is None or abs(s["value"] - want) > 0.0015):
            bad.append(f"{key} {None if s is None else round(s['value'], 4)} != {want}")
        if "hold_net_gain_pct" in e:
            h = _stat(res, "hold_net_gain_pct")
            if h is None or abs(h["value"] - e["hold_net_gain_pct"]) > TOL:
                bad.append(f"hold_net_gain_pct {h and h['value']} != {e['hold_net_gain_pct']}")
            if ("shelf_life_exceeded" in flags) != e.get("shelf_life_exceeded", False):
                bad.append("shelf_life_exceeded mismatch")
        if e.get("expected_caveat") and "no_storage_info" not in flags:
            bad.append("no_storage_info flag expected")
        if "margin_spread_pct" in e:
            sp = _stat(res, "channel_spread_pct")
            if sp is None or abs(sp["value"] - e["margin_spread_pct"]) > TOL:
                bad.append(f"channel spread {sp and sp['value']} != {e['margin_spread_pct']}")
        if "margin_squeeze" in e:
            if (("margin_squeeze" in flags) != bool(e["margin_squeeze"])):
                bad.append(f"margin_squeeze {'margin_squeeze' in flags} != {e['margin_squeeze']}")
            c = rep["species"][0]["tables"].get("costs", {})
            if c.get("top_type") != e.get("top_cost_type"):
                bad.append(f"top cost type {c.get('top_type')} != {e.get('top_cost_type')}")
            if sorted(c.get("incomplete", [])) != sorted(e.get("cost_types_incomplete", [])):
                bad.append(f"incomplete cost types {c.get('incomplete')} != {e.get('cost_types_incomplete')}")
    if qt == "sell_or_hold" and "peak_month" in e and e.get("seasonality_strength") == "strong":
        p = _stat(res, "seasonal_peak_month")
        if p is None or p["month"] != e["peak_month"] or p["reliability"] != "strong":
            bad.append("peak month mismatch")
    if qt == "best_months":
        got = [s["label"] for s in res["stats"] if s["kind"] == "best_month_score"]
        if got != e["best_months_top3"]:
            bad.append(f"best months {got} != {e['best_months_top3']}")
    if qt == "compare_markets":
        t = rep["species"][0]["tables"]["markets"]
        got = [(r["market_id"], r["net_price"]) for r in t["ranking"][:3]]
        want = [(r["market_id"], r["net_price"]) for r in e["ranking_top3"]]
        if [g[0] for g in got] != [w[0] for w in want] or any(abs(g[1] - w[1]) > 0.02 for g, w in zip(got, want)):
            bad.append(f"market ranking {got} != {want}")
        if sorted(r["market_id"] for r in t["excluded"]) != sorted(r["market_id"] for r in e["excluded_markets"]):
            bad.append("excluded markets differ")
    if qt == "best_buyer_type":
        t = rep["species"][0]["tables"]["buyers"]
        got = [(r["buyer_type"], r["net_price"]) for r in t["ranking"]]
        want = [(r["buyer_type"], r["net_price"]) for r in e["ranking_top3"]]
        if [g[0] for g in got] != [w[0] for w in want] or any(abs(g[1] - w[1]) > 0.02 for g, w in zip(got, want)):
            bad.append(f"buyer ranking {got} != {want}")
        if t["grade_used"] != e["grade_used"] or t["grade_verified"] != e["grade_verified"]:
            bad.append("grade used/verified mismatch")
        if sorted(t["excluded"]) != sorted(e["excluded_buyers"]):
            bad.append("excluded buyers differ")
    if "per_species" in e:
        for want in e["per_species"]:
            got = res["decision"]["by_series"].get(f"{want['species']}|{case['profile']['region']}")
            if got != want["direction"]:
                bad.append(f"{want['species']} direction {got} != {want['direction']}")
        if res["analysis"]["direction"] != "per_species":
            bad.append("multi-species result must be per_species")
    if e.get("out_of_scope_parts") and "note_out_of_scope" not in flags:
        bad.append("note_out_of_scope flag expected")
    if e.get("profile_conflict") and "profile_conflict" not in flags:
        bad.append("profile_conflict flag expected")
    blob = " ".join([rep["summary_md"], rep["headline"]] + [c["text"] for c in rep["claims"]]).lower()
    for ph in e.get("must_not_contain", []):
        if ph.lower() in blob:
            bad.append(f"output contains {ph!r}")
        if model_inputs and any(ph.lower() in m.lower() for m in model_inputs) and not case["profile"].get("free_text"):
            bad.append(f"model input contains {ph!r}")
    return bad
