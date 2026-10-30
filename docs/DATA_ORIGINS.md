# Data origins and the fallback ladder

Every number in an answer carries an origin tag; REAL and SYNTHETIC numbers are never combined.

| Rung | Source | Origin | Confidence |
|---|---|---|---|
| 1 | NOAA FOSS landings (+CPI) | REAL | High/Medium |
| 1 | GBIF occurrences (lake) | REAL (or TEST FIXTURE) | Medium (Low for the fixture) |
| 2 | Live free APIs (Census trade, OBIS, OECD aquaculture, NOAA FishWatch) and sourced mini-wiki notes | REAL (other public source) | Medium |
| 3 | Fictional demo market data | FICTIONAL | Low |
| 4 | Seeded synthetic profile anchored to the NOAA annual price | SYNTHETIC | Low |

Notes for integrating the real GBIF download:
- `python -m fishmarket.lake inspect <download>` then `python -m fishmarket.lake build <download>`; output goes to `lake/` (env `FISHMARKET_LAKE`).
- The lake is chunked pandas; swapping in DuckDB/Parquet is optional later.
- `data_real/crosswalk/region_boxes.csv` uses approximate boxes, not polygons: replace for real analysis.
- Review `lake/crosswalk/` review CSV for species that did not match NOAA names.
- The bundled fixture (`tests/fixtures/gbif_test_fixture.tsv.gz`) is synthetic, with fake taxon keys.

## Scenario demo and real data
The scenario demo's prices, markets and costs are fictional. Since this update, each scenario run also looks up the same
species in the real databases (`src/fishmarket/scenario_context.py`, mapped through `data_real/crosswalk/scenario_species.csv`
and `scenario_regions.csv`): NOAA U.S. dockside price and trend, wiki stock status and rules, and OECD farmed production.
The report shows these in a separate "Real U.S. data" panel with sources. The analyst and summary agents receive the same facts
as words only (every number removed), may use them only to frame risks, must label them "real U.S. data", and can never use
them in claims or to change the direction. Turn off with `SCENARIO_REAL_CONTEXT=False` in config.
