# FishMarket AI: build prompt

> **For the team (delete this box before pasting).**
> 1. Make a new empty repo folder and unzip `fishmarket_ai_starter.zip` into it, so `fishmarket_data/` sits in the repo root.
> 2. Put the $40 key in your shell as `ANTHROPIC_API_KEY`. Never commit it.
> 3. Open your coding assistant in the repo and paste everything below the line. Ask it for its plan first.
> 4. The product requirements doc is the source of truth for *what* we build. Where this prompt is more specific, this prompt wins.

---

You are building **FishMarket AI**, a demo of a multi-agent marketing assistant for fishers, cooperatives, small distributors, and fish farmers. A user describes their business (US region, operation type, species, customer segment, monthly volume). A pipeline of **eight steps with exactly three paid AI agents and Python in between** returns a one-page plain-language recommendation: sell now, or hold over the next three months. The report shows a confidence rating, caveats, where every number came from, charts, and what the run cost.

**All data is fictional.** No real market, agency, price, or company is represented, and nothing may be fetched from the internet. The point of the demo is a visible, trustworthy multi-agent pipeline that stays inside a **$40 Claude API budget across two weeks of testing**. Cost discipline is a feature, not an afterthought.

## 1. Hard rules

1. **Fictional data only.** The only network traffic allowed is the Anthropic API, and only through `src/fishmarket/llm.py`. No scraping, downloading, or web lookups.
2. **The date is fixed.** Every run takes `as_of` from the profile (default `2026-10-15`). Never call `datetime.now()` or `date.today()` in pipeline logic. Timestamps in logs are fine.
3. **No peeking.** Pipeline and app code must never read `fishmarket_data/tests_only/`. It may read `fishmarket_data/planted/` only through an explicit `overrides` argument that the tests and the "planted problems" UI toggles pass in. Add a test that fails if `tests_only` appears anywhere under `src/` or `app/`.
4. **Models never calculate.** Python computes every statistic. Models only interpret numbers that Python computed and numbered.
5. **Exactly three paid AI agents**, with bounded retries: at most one retry per loop, so a run makes **3 paid calls normally and 5 at worst**. The summary agent is never retried (see step 7).
6. **Every model call goes through `llm.py`** (modes, cache, ledger, spend guard). No other module imports the Anthropic SDK.
7. **No secrets in the repo.** Read the key from `ANTHROPIC_API_KEY`. Never print it or write it to logs, traces, or cache files.
8. **Label everything.** A persistent "Fictional data, not real market prices" banner in the UI and a line in every report.
9. **Never fall back silently.** Every retry, fallback, and repair appears in the run trace and the UI.
10. **Do not edit generated files** in `fishmarket_data/`. If the data must change, change `tools/generate_data.py`, regenerate, and rerun `tools/validate_data.py`, which must print `48 of 48 checks passed`.
11. **Develop on the free path.** Unit tests use `FakeLLM`. Manual runs default to `auto` mode (cache first). Live API calls happen only when needed and are logged to the ledger.

## 2. The starter data (already generated and validated)

```
fishmarket_data/
  README.md                        read this first
  registry/source_registry.csv     the five approved sources
  registry/species_catalog.csv     10 species: category, source_type, regions
  data/gov_landings.csv            SRC-GOV-01  Tier A  wild-catch first-sale price + landings
  data/gov_aquaculture.csv         SRC-GOV-02  Tier A  farm-gate price + harvest
  data/assoc_wholesale.csv         SRC-IND-01  Tier B  wholesale price + member volume
  data/trade_price_notes.csv       SRC-TRD-01  Tier C  price quotes only, noisier, no volume
  data/sample_fallback.csv         SRC-SMP-01  Tier D  last 24 months, fallback only
  planted/                         five defective source files, registry_planted.csv, planted_manifest.json
  tests_only/                      ground_truth.json, golden_cases.json (tests and evals only)
  tools/generate_data.py, validate_data.py
```

**Columns in every data file:** `date` (first of month), `region`, `species`, `source_type`, `price`, `volume`, `unit`, `channel`, `source_id`, `retrieved_on`.
**Registry columns:** `source_id, name, owner, source_kind, trust_tier, update_cadence_days, last_updated, file, has_volume, price_basis, expected_markup_vs_first_sale, covers, notes`.

**Facts you must respect**

- Data covers **2022-01 to 2026-09** (57 months). Demo date is **2026-10-15**, so "this month" is October and "the next three months" are November, December, and January.
- **17 series** (species | region): American lobster | Northeast; Sea scallops | Northeast; Wild salmon | Pacific Northwest; Farmed salmon | Northeast; Farmed salmon | Pacific Northwest; Gulf shrimp | Gulf; Gulf shrimp | Southeast; Cod | Northeast; Cod | Pacific Northwest; Yellowfin tuna | Gulf; Yellowfin tuna | Southeast; Catfish | Southeast; Catfish | Gulf; Tilapia | Southeast; Tilapia | Gulf; Sturgeon caviar | Pacific Northwest; Sturgeon caviar | Southeast. The intake form must only offer species that `species_catalog.csv` lists for the chosen region.
- Business types: `wild_catch`, `aquaculture`, `cooperative`, `distributor`. Customer segments: `premium`, `mainstream`, `price_sensitive`.
- **Price bases differ.** Government and trade-press prices are first-sale. Wholesale (`SRC-IND-01`) runs about 15% higher: divide by the registry's `expected_markup_vs_first_sale` (1.15) before comparing.
- **Never cross-check volumes.** Wholesale volume covers association members only (about 60% of the government figure) and trade press has no volume at all (`has_volume` is `false`, so blank volume there is not an error). Use volume only from the primary source.
- Wild salmon | Pacific Northwest and Sturgeon caviar | Southeast have **exactly one real source**. Every other series has at least two.
- The registry's `covers` column is a human hint. Determine real coverage by reading the files.
- The `unit` column is `lb` everywhere except the planted unit-error file (`kg`).
- Read `planted/planted_manifest.json`: each case lists the file, the source it replaces, the registry file to use, `expected_flags_by_series` (the exact flags each affected series must show), and the expected trust. All paths in it are relative to `fishmarket_data/`.

## 3. Stack

Python 3.11+, `pandas`, `numpy`, `anthropic` (official SDK), `streamlit` (UI and charts), `pytest`, `pydantic` (schemas). Pin versions in `requirements.txt`. The "data lake" is the local `fishmarket_data/` folder read with pandas.

## 4. Configuration (`src/fishmarket/config.py`, all values overridable)

| Setting | Default |
| --- | --- |
| `AS_OF_DEFAULT` | `2026-10-15` |
| `HOLD_THRESHOLD` | `1.10` (hold if best-next-3 seasonal index is at least this multiple of this month's) |
| `TREND_THRESHOLD_PCT` | `2.0` (year-over-year price change that counts as a trend) |
| `SEASONALITY_STRONG_SPREAD` | `0.18` (max minus min of the seasonal index; the data separates cleanly: strong series measure at least 0.26, weak ones at most 0.10) |
| `STALE_FACTOR` / `AGING_FACTOR` | `2.0` / `1.5` (times `update_cadence_days`) |
| `MAX_DATA_AGE_MONTHS` | `3` (latest data month versus `as_of`) |
| `OUTLIER_BAND` | price above 2.0x or below 0.5x the median of the other months within plus or minus 6 months |
| `KG_TO_LB` | `2.2046` |
| `MIN_CLEAN_MONTHS` | `24` |
| `DISAGREEMENT_MEDIAN_PCT` | `10` (median absolute deviation over the last 6 overlapping months) |
| `MAX_TOKENS` | agent 1: 600, agent 2: 1800, summary: 1200 |
| `PER_RUN_LIMIT_USD` / `GLOBAL_STOP_USD` | `0.25` / `34.00` |
| `MODEL_MIX["dev"]` | all three agents `claude-haiku-5-5` |
| `MODEL_MIX["final"]` | agent 1 `claude-haiku-5-5`, agent 2 `claude-sonnet-5-5`, summary `claude-haiku-5-5` |

Verify the model IDs against Anthropic's docs before the first live call. Put prices in `pricing.json` (USD per million tokens) and treat them as unverified until someone checks Anthropic's pricing page:

```
claude-haiku-5-5   input 0.10  output 0.50  (prompts over 100,000 tokens cost 5x on every line: keep prompts far below that)
claude-sonnet-5-5  input 2.00  output 10.00
```

Prompt caching is **off by default** (`ENABLE_PROMPT_CACHING=false`) because the system prompts are short. If it is ever enabled, assume the conservative cache-read price ($0.20 per million for Sonnet) because published figures disagree.

## 5. The pipeline (eight steps, in order)

Every step emits a trace event (section 8). Python steps are free; only steps 2, 5, and 7 call a model.

### Step 1. Profile and request brief (Python)

Validate the profile: `region` in the four regions; `business_type` and `customer_segment` in their lists; `species` is a **list of exactly one** species offered in that region (reject longer lists with a clear message until Phase 4); `volume_lb_per_month` greater than 0; `as_of` a valid date. Build one `RequestBrief` with the profile, the target series (`species|region`), and the decision question ("Should I sell now or hold over the next 3 months?").

### Step 2. Agent 1, retrieval planner (AI, small model)

Input: the brief plus the registry rows (`source_id, trust_tier, covers, has_volume, price_basis, last_updated, notes`). No data. Output through a forced tool call `submit_plan`:

```
{ "sources": ["SRC-GOV-01", ...], "primary_source_id": "SRC-GOV-01", "rationale": "<= 50 words" }
```

**Python enforces the plan policy** and the plan is invalid if any rule fails: every id is in the registry; each chosen source actually contains the target series (check the file); the plan includes **every Tier A, B, and C source that covers the series** (cross-checking is mandatory); Tier D is included only when no other source covers the series; `primary_source_id` is the highest-tier chosen source. Python then loads each chosen file and filters to the series. All history is loaded. `overrides` has the shape `{ "registry_path": str | null, "source_files": { source_id: path } }` and is built from `planted_manifest.json` (`registry_file`, `replaces_source_id`, `file`); with no overrides the normal registry and files are used.

**Agent 1 may be called at most twice per run.** The retry budget is shared between two failure kinds:

- *Plan invalid:* retry once with the violation list. If the second plan is also invalid, use the **deterministic default plan** (all covering Tier A, B, and C sources, highest tier primary) and record `python_default_plan` in the trace.
- *Gate hard failure* (step 3): retry once with the gate's failure report. If it fails again, **fall back to `SRC-SMP-01`**, flag `fallback_sample_data`, and cap trust at Low. If both Agent 1 calls were already used on an invalid plan, skip the retry and fall back directly.

### Step 3. Verification gate (Python, free)

Run these checks per source and per series, in this order. Repair what can be repaired, record every action, never invent values.

1. **Schema.** Required columns, parseable dates and numbers, species and region valid for the catalog, `source_type` consistent with the catalog, no non-positive price or volume (drop and flag `schema`). Unknown `unit` values: drop and flag `schema`.
2. **Unit.** Rows with `unit == "kg"`: price per lb = price / 2.2046, volume in lb = volume x 2.2046, set `unit = lb`, flag `unit_mismatch` with the row count.
3. **Duplicates.** Drop repeats of (`species`, `region`, `date`), keep the first, flag `duplicates` with the count.
4. **Date range.** Drop rows dated after `as_of`, flag `date_range` with the count.
5. **Missing values.** Drop rows with no price and flag `missing_values` with the count. A blank volume is flagged only when the registry says `has_volume` is `true`; keep the row with a blank volume.
6. **Outliers.** Drop a month whose price falls outside `OUTLIER_BAND` and flag `outlier`. Run this after unit conversion. The suite must prove **zero outlier flags on all clean data**.
7. **Freshness.** Age = `as_of` minus the registry's `last_updated`. If age is more than `STALE_FACTOR` x cadence, or the latest data month is more than `MAX_DATA_AGE_MONTHS` before `as_of`, the source is **stale**: exclude it and flag `stale_data`. If age is between `AGING_FACTOR` x and `STALE_FACTOR` x cadence, keep it and flag `aging_data`.
8. **Cross-source agreement (price only).** Compare each other usable source with the primary over their last 6 overlapping months, after dividing wholesale by its markup. If the median absolute relative deviation exceeds `DISAGREEMENT_MEDIAN_PCT`, flag `source_disagreement` and name the pair. Run it after the repairs above so repaired rows do not cause false alarms.
9. **Source count.** If exactly one usable source remains for the series, flag `single_source`.

**Hard failure** means: no usable rows for the series after cleaning, or fewer than `MIN_CLEAN_MONTHS` clean months from the primary source.

Output a `GateReport`: per source and series, the flags with counts, the rows kept and dropped, whether the source is usable, plus the clean series from the primary source.

**Trust rating** (`trust.py`, pure function, applied per series; first matching rule wins):

1. **Low** if: `fallback_sample_data`; or the only usable sources are Tier C or D; or `source_disagreement`.
2. **Medium** if: exactly one usable Tier A or B source (`single_source`); or any data-quality flag on a usable source (`unit_mismatch`, `outlier`, `duplicates`, `missing_values`, `date_range`, `aging_data`); or `stale_data` (any selected source was excluded as stale).
3. **High** otherwise: at least two usable sources that agree, at least one Tier A or B, and no flags.

Return `{ "rating": "high|medium|low", "reasons": [plain-language strings] }`. Confidence in the final report **comes only from this function, never from a model**.

### Step 4. Analytics engine (Python, free)

From the primary source's clean series, compute these statistics. Each gets an ID `S1, S2, ...` assigned sequentially:

| kind | definition | unit |
| --- | --- | --- |
| `seasonal_index_now` | seasonal index of `as_of`'s calendar month | index |
| `seasonal_index_best_next3` | the highest seasonal index among the next 3 calendar months (wrapping the year), with that month's name | index |
| `best_next3_vs_now_ratio` | the previous divided by `seasonal_index_now` | ratio |
| `seasonal_peak_month` | the month with the highest seasonal index, plus `reliability`: `strong` if max minus min of the index is at least `SEASONALITY_STRONG_SPREAD`, else `weak` | index |
| `yoy_price_change_pct` | mean price of the latest 12 calendar months divided by the mean price of the 12 months before that, minus 1, in percent; unavailable if either window has fewer than 9 observations | percent |
| `supply_yoy_change_pct` | mean volume of the latest 3 data months divided by the mean volume of the same 3 months a year earlier, minus 1, in percent | percent |
| `latest_price` | price in the latest data month | usd_per_lb |

**Seasonal index definition (must match exactly, the tests rely on it):** for each *complete* calendar year before `as_of`'s year (all 12 monthly prices present), divide each month's price by that year's mean price, then average those ratios by calendar month. For `as_of` 2026-10 the complete years are 2022 to 2025. If no complete year exists, the seasonal statistics are unavailable.

Each stat row: `{ id, series, kind, value, unit, month|null, reliability|null, window, source_id, n_obs }`. Keep full precision internally. Also return the 12-value seasonal index and the price history for the charts.

### Step 5. Agent 2, analyst (AI, mid-size model)

Input: the profile, the statistics table, the trust rating and reasons, and the decision rule. Output through a forced tool call `submit_analysis`:

```
{
  "direction": "hold | sell_now | insufficient_data",
  "timing_window": "months only, for example 'through December'",
  "headline": "max 25 words",
  "claims": [ { "id": "C1", "text": "max 40 words", "stat_ids": ["S3"],
                "numbers": [ { "value": 1.36, "stat_id": "S3" } ] } ],      // 3 to 6 claims
  "driver_tags": ["seasonal_peak_ahead", "rising_trend", "declining_trend"],  // subset
  "actions": [ { "text": "max 30 words", "claim_ids": ["C1"] } ],              // 2 to 4
  "lens_notes": { "region": "max 40 words", "business_type": "max 40 words", "customer": "max 40 words" }
}
```

The three **lenses are sections of Agent 2's prompt, not separate agents.** They change wording and actions, never numbers.

### Step 6. Grounding check (Python, free)

Reject the analysis if any rule fails:

- **G1.** Every claim cites at least one `stat_id`, and every cited id exists.
- **G2.** Numbers. Extract every numeral from each claim's text with a regular expression. Ignore four-digit years (2000 to 2100) and numerals directly followed by `month`, `months`, `year`, `years`, or `week`. Every other numeral must appear in that claim's `numbers`. Every declared number must **equal its statistic's value rounded half-up to the declared number's own decimal places** (use `decimal` with `ROUND_HALF_UP`, not Python's banker's rounding). Compare magnitudes, because prose says "fell 2.8%" for a value of -2.83. This means G2 cannot catch a wrongly signed description; do not try to solve that with word lists, the human and judge spot-checks cover it.
- **G3.** Direction follows the rule: `hold` if `best_next3_vs_now_ratio >= HOLD_THRESHOLD`, `sell_now` if below, `insufficient_data` only if that statistic is unavailable.
- **G4.** `driver_tags` equal the rule-derived set exactly: `seasonal_peak_ahead` iff direction is `hold`; `declining_trend` iff `yoy_price_change_pct <= -TREND_THRESHOLD_PCT`; `rising_trend` iff it is `>= TREND_THRESHOLD_PCT`.
- **G5.** Every `claim_ids` reference in actions exists.
- **G6.** A seasonal peak month may be stated only if its stat has `reliability == "strong"`.

On failure, **retry Agent 2 once** with the same system prompt and user message plus a short list of the violations (do not resend the previous output). On a second failure, produce the **cautious answer** with Python: direction by the rule, claims built from templates over the statistics, no lens notes, and the report labelled "The AI analyst's explanation could not be verified, so only computed statistics and the rule-based direction are shown." Record `cautious_answer` in the trace.

### Step 7. Summary agent (AI, small model)

Input: the verified claims, actions, direction, timing window, the trust rating with reasons, and the gate caveat sentences (the table in step 8). Output is plain markdown of at most 250 words with exactly these headings: `## Recommendation` (one sentence), `## Why` (three short bullets), `## What to do` (two or three bullets), `## How sure we are` (starts with `Confidence: <rating>.`).

Python checks: all four headings present; `Confidence: <rating>` matches the Python rating exactly; every numeral appears in the verified claims (same exemptions as G2); at most 300 words. If any check fails, **do not retry**: render the same four sections from a deterministic template. Record `template_summary` in the trace. In the early phases, when Agent 2 does not exist yet, feed this agent the template claims.

### Step 8. Final report (Python)

Assemble: the "Fictional data" line; recommendation, timing window, and headline; the summary; confidence and reasons; caveats; a **provenance table** (each source used with tier, last-updated date, rows used, and flags); chart data; and the cost of the run. The caveats are **fixed sentences added by Python regardless of what the models wrote**:

| Flag | Sentence |
| --- | --- |
| `single_source` | Only one approved source covers this market, so the figures could not be cross-checked. |
| `source_disagreement` | Two sources disagree on recent prices, so treat this recommendation with extra care. |
| `stale_data` | A source was left out because it has not been updated recently enough. |
| `aging_data` | A source is getting old and was used with reduced confidence. |
| `unit_mismatch` | Some rows were reported in kilograms and were converted to pounds. |
| `outlier` | One or more prices looked wrong and were removed. |
| `duplicates` | Duplicate rows were removed. |
| `missing_values` | Some rows had missing values and were skipped, not estimated. |
| `date_range` | Rows dated after today were removed. |
| `fallback_sample_data` | No approved source could be verified, so labelled sample data was used. |
| `cautious_answer` | The AI analyst's explanation could not be verified, so only computed statistics and the rule-based direction are shown. |
| `template_summary` | The written summary was generated from a fixed template. |

## 6. Agent prompts (drafts, keep in `src/fishmarket/agents/prompts/*.md` with a `PROMPT_VERSION` constant)

**Agent 1, retrieval planner**

> You are the retrieval planner in a seafood market analysis pipeline. All data is fictional. You receive a request brief and a registry of approved data sources. Choose which sources to query for the requested species and region. Rules: use only source_ids from the registry. Include every source of tier A, B, or C that covers the requested species and region, because cross-checking between sources is mandatory. Do not include tier D (sample data) unless nothing else covers the series. Set primary_source_id to the highest-tier source you included. You cannot see the data; the registry's "covers" text is a hint, so if you are unsure whether a source covers the series, include it. Reply only by calling submit_plan. Keep the rationale under 50 words and name any source you left out and why.

**Agent 2, analyst**

> You are the market analyst in a seafood market analysis pipeline. All data is fictional. You receive a business profile, a table of statistics (each with an id), data-quality notes, and a decision rule. Never calculate, estimate, or introduce a number that is not in the statistics table. Never state facts about the world that are not in the table or the profile: no weather, regulations, news, causes, or other markets. You may name the month of a seasonal peak but not explain why it happens. Mention a seasonal peak month only if its reliability is "strong".
> Decision rule: direction is "hold" if best_next3_vs_now_ratio is at least 1.10, otherwise "sell_now"; use "insufficient_data" only if that statistic is missing. Driver tags: seasonal_peak_ahead when direction is hold; declining_trend if yoy_price_change_pct is -2.0 or lower; rising_trend if it is 2.0 or higher.
> Write 3 to 6 claims. Each cites at least one stat_id and lists every number it uses with the stat_id it came from, written exactly as rounded in your text. Then write 2 to 4 actions. Tailor wording, never numbers, with these lenses:
> - Region: name the region and refer only to figures for that region.
> - Business type: wild_catch means frame actions as selling at landing versus storing to sell later, "if you can store"; aquaculture means harvest and release timing can shift toward the window; cooperative means pooled volume, so stagger sales across the window; distributor means purchase and resale timing and the margin between them.
> - Customer: premium means quality and provenance matter more than volume; mainstream means reliable supply and consistent pricing; price_sensitive means steady volume and low cost matter, and waiting for a small gain may not pay.
> Reply only by calling submit_analysis.

**Summary agent**

> You write the one-page summary for a fisher or small seafood business owner. Use plain words and short sentences; no jargon, no hype, and never mention agents, pipelines, or AI. Use only numbers that appear in the verified claims. Format exactly: "## Recommendation" with one sentence; "## Why" with three short bullets; "## What to do" with two or three short bullets; "## How sure we are" starting with "Confidence: <rating>." and then the reasons and caveats in plain words. Maximum 250 words.

## 7. LLM wrapper (`llm.py`)

- One entry point: `call(agent, system, user, tool_schema, model, max_tokens, run_ctx)` returning `{tool_input, usage, cost_usd, cache: "hit" | "miss", model}`. Use a forced tool call (`tool_choice` set to the named tool) so output is structured JSON, validated with pydantic. Use low temperature where the API accepts it; otherwise omit it.
- **Modes** (set by `LLM_MODE`, default `auto`): `live` always calls and stores the result; `auto` uses the cache and calls on a miss; `replay` uses only the cache and raises a friendly `ReplayMiss` otherwise (this is the safe demo mode); a `FakeLLM` class is injected by tests and costs nothing.
- **Cache** keyed by the SHA-256 of a canonical JSON of model, system, user, tool schema, max_tokens, temperature, and `PROMPT_VERSION`. Files in `cache/`. `cache/approved/` is committed as the demo backup, everything else in `cache/` is git-ignored.
- **Ledger** `ledger.jsonl`: one line per call with timestamp, run id, agent, model, input and output tokens, cache result, `cost_usd` (0 for cache hits), and mode. The cost uses the API's reported `usage` and `pricing.json`.
- **Spend guard.** Before any live call, estimate the worst case (input characters / 3.5 as tokens, plus `max_tokens` of output). Raise `BudgetExceeded` if the run total would exceed `PER_RUN_LIMIT_USD` or the ledger total would exceed `GLOBAL_STOP_USD`. The UI shows the remaining budget.
- Handle API errors cleanly (rate limit, network): surface them in the trace and never loop.

## 8. Run trace and UI

**Events.** One per step and attempt: `{ run_id, step, status, attempt, started_at, ended_at, headline, detail, tokens_in, tokens_out, cost_usd, cache }`, where `step` is one of `profile, agent1, gate, analytics, agent2, grounding, summary, report` and `status` is one of `pending, running, done, warning, retrying, failed, fallback`. `pipeline.run(profile, overrides=None, on_event=callback)` calls `on_event` as steps progress so the UI can update live. Save each run to `runs/<run_id>.json`.

**Streamlit app (`app/streamlit_app.py`)**

- **Persistent banner:** "Fictional data, not real market prices." Sidebar: LLM mode, model mix (`dev` or `final`), preset picker (G01 to G06: copy the six preset profiles from `tests_only/golden_cases.json` into `app/presets.json` once, with a one-off script; the app reads only `app/presets.json`), budget meter (spent, remaining, global stop).
- **Profile screen:** one short form (region, operation type, species filtered by region, customer segment, volume) plus preset buttons.
- **Run screen:** eight cards, one per step, updating live; AI cards are visually distinct from Python cards; each shows status, a one-line headline, and the cost; failed checks, retries, and fallbacks are shown plainly in colour and words.
- **Result screen:** recommendation first, then the summary, the confidence rating with reasons, the caveats, the provenance table, a price-history chart with the seasonal index and the next three months highlighted, the run cost, and an expander per step with the raw output.
- **Planted-problem toggles:** a checkbox per case (`PP-STALE`, `PP-UNIT`, `PP-OUTLIER`, `PP-CONFLICT`, `PP-DUPMISS`) that passes the matching `overrides`. Two cases that replace the same source id cannot both be on; disable the conflicting one and say why.

## 9. Tests and evals

**Level 1, free (`pytest`)**
- `test_data_validates`: runs `tools/validate_data.py` logic on the dataset.
- `test_no_tests_only_reads`: nothing under `src/` or `app/` mentions `tests_only`.
- Gate: clean data across all 17 series produces **no flags except** `single_source` on the two single-source series; each planted case changes exactly the series listed in its manifest's `expected_flags_by_series`, produces those flags on them, and gives the manifest's `expected_trust_for_affected_series` (PP-DUPMISS plants a different defect in each of its four series); after repair, the kg case matches the clean data within 0.5%, the outlier month is gone, no duplicates or future rows remain, and no blank price was invented.
- Trust: table-driven cases covering every rule and the precedence between them.
- Analytics: for all 17 series, the seasonal index and ratio match `tests_only/ground_truth.json` within 0.002, year-over-year change within 0.05 points, supply change within 0.05 points, and `seasonal_peak_month` matches for strong series.
- Grounding: rejects a fabricated number, an unknown stat id, the wrong direction, a wrong driver tag, and a peak month on a weak series; accepts a correct analysis; rounding uses half-up.
- LLM wrapper: a cache hit costs zero; `replay` raises on a miss; the spend guard blocks the call that would pass the limit; no secret appears in any file the wrapper writes.
- Pipeline with `FakeLLM`, scripted by small helper functions that build schema-valid outputs from the inputs (for example, a fake analyst that writes claims from the statistics table): for all 12 golden profiles, direction, trust, gate flags, and driver tags match the golden expectations. Also cover each retry and fallback path (invalid plan, hard gate failure, grounding failure twice, summary check failure) and assert the paid-call count never exceeds 5.

**Level 2, free: replay regression.** Run the six presets in `replay` mode against `cache/approved/` and compare the normalized result (drop run ids and timestamps) with `tests/snapshots/<preset>.json`. Add `scripts/approve.py <preset>` to refresh a snapshot and its cache entries after an intentional prompt change.

**Level 3, paid but cheap: golden evaluation.** `python -m evals.run_golden --mix dev|final --mode auto|live [--cases G01,G02]` runs the 12 cases in `tests_only/golden_cases.json` and scores each case automatically: direction; trust rating; every `required_gate_flags` present; `required_driver_tags` present and `forbidden_driver_tags` absent; at least `min_cited_stats` cited statistics covering every kind in `required_stat_kinds`; grounding passed without falling back to the cautious answer; and, when `peak_month` is set, the analytics statistic matches it with `reliability == "strong"` (when it is null the reliability must be `weak`). Also report grounding retries, fallbacks, summary-template uses, tokens, and cost per case, and write `evals/results/<timestamp>-<PROMPT_VERSION>-<mix>.json`. Refuse a live `final` run expected to cost more than $1 unless `--yes` is passed. Expected cost: about 3 cents for a `dev` pass and about 35 cents for a `final` pass.

Run live evaluations only after a prompt or model change, once per case; rerun a failing case once to separate real failure from model variation.

**Optional Level 4:** a judge pass with the small model that scores each summary 1 to 5 for readability and tone, off by default, one call per report.

## 10. Project layout

```
src/fishmarket/  config.py  schemas.py  registry.py  loader.py  llm.py  gate.py  trust.py
                 analytics.py  grounding.py  report.py  pipeline.py  events.py  cli.py
                 agents/  agent1.py  agent2.py  summary.py  templates.py  prompts/
app/             streamlit_app.py  presets.json
tests/           (level 1 and 2)      evals/  run_golden.py  results/
scripts/         approve.py            cache/  approved/        runs/
fishmarket_data/ (provided, do not edit)    pricing.json   requirements.txt   .gitignore
```

Git-ignore: `.env`, `runs/`, `ledger.jsonl`, `evals/results/`, everything in `cache/` except `cache/approved/`.

## 11. Build order and acceptance criteria

Build one phase at a time. **At the end of each phase run `pytest -q` and `python fishmarket_data/tools/validate_data.py fishmarket_data`, print what was built, what was not, and the total spend from the ledger, then stop and wait for me to say continue.**

**Phase 0, scaffold.** Repo layout, config, pricing file, registry loader, requirements, `.gitignore`, the guard test for rule 3. *Accept:* tests green, validator passes.

**Phase 1, thin slice.** Profile validation; `llm.py` with all modes, ledger, spend guard, and `FakeLLM`; Agent 1 with plan policy and the loader; gate checks 1, 2, 3, 4, 5, 7, and 9; the trust function (pure and fully unit-tested now, since the summary must state the Python-computed confidence); analytics statistics; template claims; the summary agent with its checks and template fallback; a CLI `python -m fishmarket.cli run --preset G01`. *Accept:* G01 prints a readable summary; running it again in `auto` mode costs $0.00; the gate, trust, and analytics tests pass for all 17 series.

**Phase 2, full pipeline.** Agent 2 with lenses, the grounding check, both retry loops, the cautious answer, the default plan, and the sample fallback. *Accept:* all 12 golden profiles pass with `FakeLLM`; every retry and fallback path is tested; a live `dev` run of G01 to G05 costs under $0.10 in total.

**Phase 3, verification depth and visibility.** Gate checks 6 and 8 (outliers, cross-source) with trust verified against every planted case, caveats, provenance table, planted-problem overrides, the Streamlit app with the live run screen, charts, cost meter, presets, and the golden evaluation script. *Accept:* every planted case is caught with its expected flags and trust; G06 shows the conflict and stale-source handling in the UI; a full `dev` golden pass costs under $0.10; a `final` pass costs under $0.60.

**Phase 4, stretch (only with budget left).** Up to three species per run, the QA critic, export to PDF or Markdown, follow-up questions, the judge pass.

## 12. Working agreement

- **Plan first.** Read `fishmarket_data/README.md`, the registry, and `golden_cases.json`, then reply with a short plan and any questions. Wait for my go-ahead before writing code.
- Stay inside the current phase. Do not add features, dependencies, or abstractions I did not ask for.
- If anything here conflicts with what is on disk, trust the data and tell me.
- Ask before changing any threshold in section 4 or any prompt in section 6, and bump `PROMPT_VERSION` when a prompt changes.
- Do not call the live API from your own tooling while developing. Use the project's wrapper in `auto` or `replay` mode, or `FakeLLM`.
- Report the ledger total at the end of every phase. The whole project must fit in $40, and we stop at $34.
