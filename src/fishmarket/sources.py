"""Registry of real data sources: what is wired, what is verified, and what still needs a real endpoint.
'verified' means a request was actually answered during development. Nothing here is guessed silently."""
SOURCES = [
 {"id": "NOAA-LANDINGS", "name": "NOAA FOSS Commercial Fish Landings", "status": "in_use",
  "url": "https://apps-st.fisheries.noaa.gov/ods/foss/landings/", "how": "CSV noaa_landings_full.csv (229,828 rows, 1950-2024), refresh with scripts/extract_noaa_full.py",
  "gives": "annual pounds and dollars by species, state, region"},
 {"id": "NOAA-TRADE", "name": "NOAA FOSS Foreign Seafood Trade", "status": "fetcher_ready_unverified",
  "url": "https://apps-st.fisheries.noaa.gov/ods/foss/trade_data/", "how": "scripts/fetch_noaa_trade.py -> data_real/noaa_trade.csv",
  "gives": "import/export volume and value by product and country; useful for import price pressure"},
 {"id": "NOAA-METADATA", "name": "NOAA FOSS metadata catalog", "status": "reference_only",
  "url": "https://apps-st.fisheries.noaa.gov/ods/foss/metadata-catalog/", "how": "read to confirm field meanings", "gives": "field definitions"},
 {"id": "NOAA-VESSELS", "name": "Vessel Registry datasets", "status": "needs_real_url",
  "url": "https://noaa.gov", "how": "the supplied link is the NOAA home page, not a dataset", "gives": "unknown until a dataset URL is supplied"},
 {"id": "AFSC-SURVEY", "name": "AFSC survey inventories", "status": "needs_real_url",
  "url": "https://noaa.gov", "how": "the supplied link is the NOAA home page, not a dataset", "gives": "unknown until a dataset URL is supplied"},
 {"id": "FISHBASE", "name": "FishBase via rOpenSci API", "status": "fetcher_ready_unverified",
  "url": "https://fishbase.ropensci.org/", "how": "species_info.py calls /species?genus=&species= (documented at ropensci.github.io/fishbaseapidocs) and also tries /fishbase/species. Not reachable from the build sandbox. rfishbase itself now reads parquet tables, so the REST service may be retired. Responses pass validators.validate_fishbase.",
  "gives": "common names, biology, habitat; no prices"},
 {"id": "GBIF", "name": "GBIF species API", "status": "fetcher_ready_unverified",
  "url": "https://api.gbif.org/v1", "how": "species_info.py: species/match, vernacularNames, occurrence/search (US, with coordinates). Every match and every point passes validators.py. GBIF also has a Maps API (tiles) not used yet.",
  "gives": "taxonomy match and occurrence counts; no prices"},
]
STATUS_TEXT = {"in_use": "Live in the app", "fetcher_ready_unverified": "Script written, not yet run against the live service",
               "reference_only": "Documentation only", "needs_real_url": "Needs a real dataset link"}
