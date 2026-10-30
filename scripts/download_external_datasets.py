#!/usr/bin/env python3
"""
Download species data from GBIF and FishBase APIs to create local datasets.

This script fetches occurrence data from GBIF and species information from FishBase
for fish species, saving them as local files for offline use in the fishmarket pipeline.

Usage:
    python scripts/download_external_datasets.py --common-name "Atlantic cod" --limit 1000
    python scripts/download_external_datasets.py --from-noaa valid_for_analysis.csv --limit 500
"""
import argparse
import json
import time
import pandas as pd
import requests
from pathlib import Path
from typing import Optional, List, Dict


# Output directory
DATA_DIR = Path("external_data")
DATA_DIR.mkdir(exist_ok=True)


def get_json(url: str, params: Optional[dict] = None, tries: int = 3, verify: bool = True) -> Optional[dict]:
    """Fetch JSON from API with retries."""
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30, verify=verify)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            print(f"  Retry {i+1}/{tries}: {e}")
            if i < tries - 1:
                time.sleep(2 ** i)
    return None


def gbif_match_name(name: str) -> Optional[Dict]:
    """Try to match a name (common or scientific) in GBIF and return taxon info."""
    print(f"Matching GBIF: {name}")
    m = get_json("https://api.gbif.org/v1/species/match", {"name": name})
    if m and m.get("usageKey"):
        return {
            "key": str(m["usageKey"]),
            "scientific_name": m.get("scientificName"),
            "canonical_name": m.get("canonicalName"),
            "rank": m.get("rank"),
            "status": m.get("status"),
        }
    print(f"  No GBIF match found")
    return None


def gbif_download_occurrences(taxon_key: str, species_name: str, limit: int = 1000) -> pd.DataFrame:
    """Download occurrence records from GBIF for a taxon."""
    print(f"Downloading GBIF occurrences for {species_name} (limit: {limit})")
    all_records = []
    offset = 0
    batch_size = 300

    while offset < limit:
        print(f"  Fetching {offset} to {offset + batch_size}...")
        d = get_json(
            "https://api.gbif.org/v1/occurrence/search",
            {"taxonKey": taxon_key, "limit": batch_size, "offset": offset, "hasCoordinate": "true"}
        )

        if not d or not d.get("results"):
            break

        all_records.extend(d["results"])
        offset += batch_size

        # Respect rate limits
        time.sleep(0.2)

        if len(d["results"]) < batch_size:
            break

    print(f"  Downloaded {len(all_records)} occurrences")
    return pd.DataFrame(all_records)


def fishbase_get_species(genus: str, species: str) -> Optional[dict]:
    """Get species information from FishBase."""
    print(f"Fetching FishBase data for {genus} {species}")
    d = get_json(
        "https://fishbase.ropensci.org/species",
        {"Genus": genus, "Species": species},
        verify=False  # FishBase has SSL issues
    )
    if d and d.get("data"):
        print(f"  Found {len(d['data'])} records")
        return d["data"]
    print(f"  No FishBase data found")
    return None


def parse_scientific_name(name: str) -> tuple[Optional[str], Optional[str]]:
    """Parse a scientific name into genus and species."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def download_for_species(name: str, limit: int = 1000) -> dict:
    """Download data from both APIs for a single species."""
    print(f"\n{'='*60}")
    print(f"Processing: {name}")
    print(f"{'='*60}")

    results = {
        "input_name": name,
        "gbif_key": None,
        "gbif_scientific_name": None,
        "gbif_occurrences": 0,
        "fishbase_records": 0,
        "gbif_file": None,
        "fishbase_file": None,
    }

    # Try GBIF match (works for both common and scientific names)
    gbif_info = gbif_match_name(name)
    if gbif_info:
        results["gbif_key"] = gbif_info["key"]
        results["gbif_scientific_name"] = gbif_info.get("scientific_name")

        # Download occurrences
        gbif_df = gbif_download_occurrences(gbif_info["key"], name, limit)
        if not gbif_df.empty:
            # Save to CSV
            safe_name = name.replace(" ", "_").replace("/", "_").replace(",", "_")
            gbif_file = DATA_DIR / f"gbif_{safe_name}.csv"
            gbif_df.to_csv(gbif_file, index=False)
            results["gbif_occurrences"] = len(gbif_df)
            results["gbif_file"] = str(gbif_file)
            print(f"  Saved to: {gbif_file}")

        # Try FishBase with the scientific name from GBIF
        if gbif_info.get("canonicalName"):
            genus, species = parse_scientific_name(gbif_info["canonicalName"])
            if genus and species:
                fishbase_data = fishbase_get_species(genus, species)
                if fishbase_data:
                    safe_name = name.replace(" ", "_").replace("/", "_").replace(",", "_")
                    fishbase_file = DATA_DIR / f"fishbase_{safe_name}.json"
                    with open(fishbase_file, "w") as f:
                        json.dump(fishbase_data, f, indent=2)
                    results["fishbase_records"] = len(fishbase_data)
                    results["fishbase_file"] = str(fishbase_file)
                    print(f"  Saved to: {fishbase_file}")

    return results


def download_from_noaa(csv_path: str, limit: int = 500, max_species: int = 20) -> List[dict]:
    """Download data for species found in NOAA CSV file."""
    df = pd.read_csv(csv_path)

    # Get unique species names
    if "species" in df.columns:
        species_list = df["species"].dropna().unique()[:max_species]
    elif "ts_afs_name" in df.columns:
        species_list = df["ts_afs_name"].dropna().unique()[:max_species]
    else:
        print("Error: No species column found in CSV")
        return []

    print(f"Found {len(species_list)} unique species in {csv_path} (limited to {max_species})")

    results = []
    for i, name in enumerate(species_list, 1):
        print(f"\n[{i}/{len(species_list)}]")
        result = download_for_species(name, limit)
        results.append(result)

        # Longer delay between species to respect rate limits
        time.sleep(1)

    return results


def save_summary(results: List[dict], output_file: str = "external_data_summary.csv"):
    """Save a summary of downloads."""
    df = pd.DataFrame(results)
    df.to_csv(output_file, index=False)
    print(f"\n{'='*60}")
    print(f"Summary saved to: {output_file}")
    print(f"{'='*60}")
    print(df[["input_name", "gbif_occurrences", "fishbase_records"]].to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="Download species data from GBIF and FishBase")
    parser.add_argument(
        "--common-name",
        help="Common name of a species (e.g., 'Atlantic cod')"
    )
    parser.add_argument(
        "--scientific-name",
        help="Scientific name of a species (e.g., 'Gadus morhua')"
    )
    parser.add_argument(
        "--from-noaa",
        help="NOAA CSV file to extract species from"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum occurrences to download per species from GBIF (default: 1000)"
    )
    parser.add_argument(
        "--max-species",
        type=int,
        default=20,
        help="Maximum number of species to process from NOAA file (default: 20)"
    )
    parser.add_argument(
        "--output-dir",
        default="external_data",
        help="Directory to save downloaded data (default: external_data)"
    )

    args = parser.parse_args()

    # Update data directory
    global DATA_DIR
    DATA_DIR = Path(args.output_dir)
    DATA_DIR.mkdir(exist_ok=True)

    if args.common_name:
        # Single species by common name
        result = download_for_species(args.common_name, args.limit)
        save_summary([result])
    elif args.scientific_name:
        # Single species by scientific name
        result = download_for_species(args.scientific_name, args.limit)
        save_summary([result])
    elif args.from_noaa:
        # Multiple species from NOAA file
        results = download_from_noaa(args.from_noaa, args.limit, args.max_species)
        save_summary(results)
    else:
        print("Error: Please specify --common-name, --scientific-name, or --from-noaa")
        parser.print_help()


if __name__ == "__main__":
    main()
