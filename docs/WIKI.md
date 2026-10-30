# Mini-wiki

A short plain-text file, `data_real/wiki/wiki.md` (50 entries, about 3,300 words), covering what the NOAA landings and GBIF data
cannot tell you: terms (ex-vessel, overfished, MSY, catch shares, bycatch), stock status and rules for eight main species,
how recreational catch is estimated, gear types, seafood labeling names, histamine and cold handling, fishing seasons, and
U.S. import share, buying and cooking fish, the import-monitoring program, farmed seafood, how U.S. fisheries are managed, and fish farming (farmed Atlantic salmon, feeds, shellfish, West Coast farms), and stock status and rules for 30 species, covering the top species by U.S. landed value.

- **Format:** one `## id | Title` block per entry, then `type`, `keywords`, `species` (stock entries), `retrieved` (date) and `source` (https link) lines, then the text (15 to 110 words).
- **Check it:** `python -m fishmarket.wiki check` (add `--as-of=YYYY-MM-DD` to list entries read more than a year before that date). Search it: `python -m fishmarket.wiki search "what is a catch share"`.
- **In the app:** the Ask page routes definition and status questions ("What does ex-vessel mean?", "Is Atlantic cod overfished?") to the wiki. Answers show the entry text verbatim, are labelled "REAL (other public source)", capped at Medium confidence, and cite the entry's source link and read date. Price and landings questions still go to NOAA.
- **Adding an entry:** copy a block, keep it short and factual, paste only what the source says, and run the check. Stock status and rules go stale, so re-read the source links before a release (the `retrieved` date shows when it was last read).
- **Not in the wiki on purpose:** anything NOAA landings or GBIF already answer (prices, landings, ranges), and tips that have no public source (for example profit margins or storage costs).

## Growing it from real questions
Questions the Ask page could not answer (or had to ask a follow-up about) are logged locally to `runs/qa_misses.jsonl`
(gitignored; turn off with `FISHMARKET_LOG_MISSES=0`). See what people asked:

    python -m fishmarket.qa.misses

Write new entries for the questions that come up most, then run `python -m fishmarket.wiki check`.
