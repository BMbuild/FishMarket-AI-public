# External Species Datasets

This directory contains species occurrence and taxonomy data downloaded from external APIs (GBIF, FishBase) to supplement the NOAA fisheries data.

## Not included in this repository

The raw GBIF occurrence files (`gbif_<Species>.csv`) are **not published here**. GBIF records carry the licence
chosen by each data publisher: CC0, CC BY or CC BY-NC. In the first download, about 209,000 of 340,000 records were
CC BY-NC. Rather than redistribute them, download them yourself with the script below. The lake build
(`python -m fishmarket.lake build external_data`) excludes CC BY-NC records unless `--allow-noncommercial` is passed.

Each downloaded CSV has 121 columns, including coordinates, taxonomy, dates, dataset metadata, the record's
`license`, and GBIF quality flags (`issues`).

Data attribution: GBIF.org, occurrence search API (https://api.gbif.org/v1/), with records from the publishing
institutions named in each record's dataset metadata. Cite the retrieval date when you use a download.

### FishBase Data
FishBase provides species taxonomy, ecology, and fisheries information.
- Currently empty (FishBase API has SSL certificate issues)

## Download Script

To download additional species data:

```bash
# Single species by scientific name
python scripts/download_external_datasets.py --scientific-name "Species name" --limit 1000

# Single species by common name (may not match GBIF)
python scripts/download_external_datasets.py --common-name "Common name" --limit 1000

# Multiple species from NOAA file
python scripts/download_external_datasets.py --from-noaa valid_for_analysis.csv --limit 500 --max-species 20
```

## Usage in Pipeline

The GBIF occurrence data can be used to:
- Validate species geographic ranges
- Cross-reference NOAA landings with occurrence data
- Add spatial context to market analysis
- Identify species distribution patterns

## API Rate Limits

- GBIF: No hard limit, but respectful delays are built in (0.2s between batches, 1s between species)
- FishBase: Currently experiencing SSL certificate issues

## Data Sources

- **GBIF**: https://api.gbif.org/v1/
- **FishBase**: https://fishbase.ropensci.org/
