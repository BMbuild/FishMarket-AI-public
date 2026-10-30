"""Self-checks for the v2 dataset. Usage: python3 validate_data.py <dataset_dir> [<v1_dataset_dir>]"""
import json, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
import gen_expect as X

root = Path(sys.argv[1]); v1 = Path(sys.argv[2]) if len(sys.argv) > 2 else None
fails = []
def check(ok, msg):
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok: fails.append(msg)

ref = X.Ref(root)
gt = json.load(open(root / "tests_only/ground_truth.json"))["series"]
cases = json.load(open(root / "tests_only/golden_cases.json"))
man = json.load(open(root / "planted/planted_manifest.json"))
check(len(gt) == 64, f"64 series in ground truth ({len(gt)})")
check(len(ref.catalog) == 35 and ref.mmeta.shape[0] == 24 and ref.ops.shape[0] == 13, "35 species, 24 markets, 13 operation types")
if v1:
    for f, key in (("gov_landings", "SRC-GOV-01"), ("gov_aquaculture", "SRC-GOV-02"), ("assoc_wholesale", "SRC-IND-01"), ("trade_price_notes", "SRC-TRD-01"), ("sample_fallback", "SRC-SMP-01")):
        old = pd.read_csv(v1 / f"data/{f}.csv"); new = pd.read_csv(root / f"data/{f}.csv")
        m = old.merge(new, how="left", indicator=True)
        check((m["_merge"] == "both").all(), f"legacy rows of {f} present unchanged ({len(old)})")
ms = lambda v: max(v["measured_seasonal_price_index"]) - min(v["measured_seasonal_price_index"])
bad = [k for k, v in gt.items() if (v["seasonality_strength"] == "strong" and ms(v) < 0.22) or (v["seasonality_strength"] != "strong" and ms(v) > 0.14)]
check(not bad, f"measured seasonal spread: strong >= 0.22, mild/flat <= 0.14 (clear of the app's 0.18 cut) {bad}")
mism = [k for k, v in gt.items() if v["measured_peak_price_month"] != v["planted_peak_price_month"] and v["seasonality_strength"] == "strong"]
check(not mism, f"strong series: measured peak month equals planted ({len(mism)} mismatches)")
for s, v in gt.items():
    pass
for c in cases:
    e = c["expected"]
    for k in ("best_next3_vs_now_ratio",):
        if k in e and e.get("question_type") == "sell_or_hold" and abs(e[k] - 1.10) < 0.03:
            check(False, f"{c['case_id']} ratio {e[k]} within 0.03 of threshold")
check(all(p in {m["case_id"] for m in man} for c in cases for p in c["planted_cases"]), "all planted case ids exist in the manifest")
check(all((root / m["file"]).exists() for m in man), "all planted files exist")
q = ref.quality
check(set(q.verification_status) <= {"VERIFIED", "UNVERIFIED", "CONFLICTED"}, "quality record statuses valid")
check(len(set(c["case_id"] for c in cases)) == len(cases), "unique golden case ids")
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
