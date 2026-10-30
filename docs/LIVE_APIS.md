# Live APIs (no bulk downloads)

Two free APIs are called on demand, a few small requests per question, cached for 14 days in `cache/live/` (gitignored).
Nothing large is ever downloaded.

| Source | Used for | Key | Question types |
|---|---|---|---|
| OBIS `https://api.obis.org/v3` | record counts by decade and a small recent sample (latitude range) | none | `obis_profile` |
| U.S. Census international trade API (HS imports/exports) | U.S. seafood trade value by product heading and partner country | free `CENSUS_API_KEY` ([sign up](https://api.census.gov/data/key_signup.html)) | `seafood_trade` |

**NOAA trade:** NOAA's foreign trade database has only a web query tool and no API. Census is the official upstream source for U.S.
trade statistics, so the app calls Census directly. Trade is by HS heading (0302 to 0307: fresh/frozen fish, fillets, dried fish,
crustaceans, molluscs), not by species.

**Switching on:** put `FISHMARKET_LIVE=1` and `CENSUS_API_KEY=...` in the gitignored `.env` (or the environment). Off by default.
The key is read only when a call is made, is never cached, logged or shown in answers, and TLS is always verified.

**Check it works:** `python -m fishmarket.live check` makes a few tiny real calls to each API and reports whether the response shapes match.
This code was written and tested against a fake transport only (the build sandbox could not reach either API), so run the check first.
The OBIS response shape (`total` and `results`) is assumed from its public docs; the Census call forms come from Census's own guide.

**When a live call is off or fails** the answer never guesses. For trade the order is: live Census numbers (REAL), else a sourced wiki
note for general questions (REAL), else a labelled generated illustration (SYNTHETIC, Low confidence, not available in real-only mode).
OBIS questions simply say the lookup is off or failed.

## Generated and fictional fillers
Used only when real data cannot answer and real-only mode is off. Always labelled SYNTHETIC, Low confidence, seeded (the same
question gives the same numbers) and never combined with real numbers in one answer:
monthly price pattern (`monthly_timing`), fictional market comparison (`market_compare`), fictional costs, margin, storage and grade split
(`costs_quality_storage`), and an illustrative trade figure when live trade data is unavailable (`seafood_trade`).

## Farming sources: how species are matched
Both use the NOAA landings file's scientific name for the species. OECD species labels carry the scientific name in brackets
(for example "Atlantic salmon [Salmo salar]"), so the match is exact, with a genus fallback that is flagged. The OECD agency and
dimension order are read from OECD's own structure metadata rather than hard-coded. FishWatch is matched on scientific name, then
common name, preferring a farmed profile. "Farmed salmon" is taken to mean Atlantic salmon, and the answer says so.
**Update:** NOAA has retired the FishWatch API (it now redirects to https://www.fisheries.noaa.gov/topic/sustainable-seafood), so the
download script skips it and the farming-profile question type answers from the mini-wiki's sourced farming entries
(farmed Atlantic salmon, aquaculture feeds, shellfish farming, West Coast fish farming).

## Farming data: small local files
OECD aquaculture production and NOAA FishWatch profiles are small, so they are downloaded once instead of called live:

    python scripts/download_farming_data.py

This writes `data_real/oecd/aquaculture_production.csv` (OECD Data Explorer, dataflow `DSD_FISH_PROD@DF_FISH_AQUA`, agency read from
OECD's metadata) then prints row counts. (FishWatch is skipped: its API has been retired.) Re-run it to
refresh. The question types `aquaculture_production` ("How much Atlantic salmon does the US farm?") and `farming_profile`
("What do farmed salmon eat?") read these files; with FISHMARKET_LIVE=1 and no file they fall back to live calls.

Species are matched by the NOAA landings file's scientific name: OECD species labels carry it in brackets ("Atlantic salmon [Salmo salar]"),
with a flagged genus fallback; FishWatch is matched on scientific then common name, preferring a farmed profile. "Farmed salmon" is taken
to mean Atlantic salmon and the answer says so. FishWatch text is quoted, not summarised, and can be several years old.

## OECD cleansing gate
`python -m fishmarket.oecd_clean` (run automatically by the download script) classifies every OECD row:
VALID, REVIEW (usable, with flags the answer mentions), EXCLUDED_BY_DESIGN (empty: no observation) or REJECTED
(negative, bad year, unknown unit, duplicate). Flags: IMPUTED, CARRIED_FORWARD (same as the year before), JUMP_10X,
PRICE_OUTLIER (value per kg outside $0.05-$100; no value per lb is shown), AGGREGATE ("nei" species group).
On the 2026 download: 89,056 VALID, 18,427 REVIEW, 51,389 empty, 0 rejected. The app reads
`data_real/oecd/aquaculture_clean.csv` when it is newer than the raw download.
