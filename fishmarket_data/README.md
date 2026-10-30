# FishMarket AI fictional dataset, v2

All data is fictional. Names, prices, markets, inspectors and notes are invented. The demo "today" is **2026-10-15**.

v2 adds to v1 and never edits it: all 2,574 v1 rows are byte-identical. Goldens G01-G12 still hold, except G07 and G09 (distributors), which now use the wholesale price channel their operation type sells through.

## What is in it
| Folder | Contents |
|---|---|
| `data/` | 9 CSVs: first-sale landings and farm prices (v1), wholesale (v1), trade notes (v1), fallback sample (v1), **retail survey, 24 market price postings, quality records, input costs** (new) |
| `registry/` | source registry (now with `dataset_kind`), species catalog (35), markets (24), **operation types (13)**, **customer segments (5)** |
| `reference/` | buyer channels (9), freight costs, storage profiles (64), fishing seasons, FX rates, markup table |
| `planted/` | 12 planted problem cases plus `planted_manifest.json` (the 5 v1 cases plus 7 new) |
| `tests_only/` | `ground_truth.json` (64 series), `golden_cases.json` (53 cases), `personas.json` (7 free-text personas). **Never show these to the app or to a model.** |
| `tools/` | `generate_data.py` (deterministic, seed fixed), `validate_data.py`, `gen_expect.py` |

Scale: 8 regions, 35 species, 64 species-region series, 24 markets, 6 input-cost series per region, 9 buyer types.

## Rules the goldens use (the app must implement the same ones)
- **sell_or_hold**: hold if the best of the next 3 months' seasonal index is at least 1.10 times this month's. Price channel follows the operation type (first sale, wholesale or retail).
- **buy_now_or_wait**: mean of the next 3 months' index divided by this month's. At least 1.05 is buy_now, at most 0.95 is wait, otherwise no_clear_signal.
- **best_months**: open-season months only; score = price index x volume index^0.5 for wild catch, price index for farmed; top 3, ties to the earlier month.
- **compare_markets**: net = last-3-month mean x (1 - fee/100) - freight from the user's region. A market not updated within 2x its cadence is excluded.
- **best_buyer_type**: net = 3-month first-sale mean x category multiplier x (1 - fee) x (1 - payment_days/365 x 0.08). Buyers are excluded for min order, grade, or species type. Segment fit is preferred. Grade comes only from VERIFIED quality records; with none, grade C is assumed and the report says so.
- **Quality status** (records since 2026-04-01): conflicted if any CONFLICTED; verified if at least 80% VERIFIED; partial if at least 40%; else unverified; none if no records.
- **margin_squeeze**: the largest input-cost year-over-year change minus the price year-over-year change is at least 5 points. A cost type with fewer than 9 observations in either 12-month window is incomplete and skipped.
- **hold net gain** = (ratio - 1) x 100 - (carrying + shrink % per month) x months to the best month; shelf life exceeded if max_shelf_days < 30 x months.

## Planted cases (see `planted/planted_manifest.json`)
v1: PP-STALE, PP-UNIT, PP-OUTLIER, PP-CONFLICT, PP-DUPMISS.
New: PP-RETAIL-OZ (retail priced per ounce), PP-MKT-STALE (one market stops posting), PP-MKT-CAD (market posts in Canadian dollars), PP-QUAL-UNVERIFIED, PP-QUAL-CONFLICT, PP-QUAL-INJECT (instructions hidden in inspector notes), PP-COST-GAP (six months of Southeast feed cost missing).
A case with `override_files` replaces more than one file; the app must apply them together.

## Regenerate and check
```
python3 tools/generate_data.py out_dir
python3 tools/validate_data.py out_dir <v1_dataset_dir>   # second argument optional
```
