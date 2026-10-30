#!/usr/bin/env python3
"""
Download GBIF occurrence data for ALL species found in NOAA data.

This script extracts all unique species from the NOAA CSV and attempts to
download GBIF occurrence data for each, creating a comprehensive local dataset.

Usage:
    python scripts/download_all_gbif.py --input noaa_landings_full.csv --limit 500
"""
import argparse
import json
import time
import pandas as pd
import requests
from pathlib import Path
from typing import Optional, List, Dict, Set
from concurrent.futures import ThreadPoolExecutor, as_completed


# Output directory
DATA_DIR = Path("external_data")
DATA_DIR.mkdir(exist_ok=True)

# Log file
LOG_FILE = DATA_DIR / "download_log.txt"

# Progress file for resume capability
PROGRESS_FILE = DATA_DIR / "download_progress.json"


def log(message: str):
    """Append message to log file and print."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_progress() -> Set[str]:
    """Load list of already processed species from progress file."""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r") as f:
                data = json.load(f)
                return set(data.get("processed", []))
        except Exception as e:
            log(f"Warning: Could not load progress file: {e}")
    return set()


def save_progress(processed: Set[str]):
    """Save list of processed species to progress file."""
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump({"processed": list(processed)}, f, indent=2)
    except Exception as e:
        log(f"Warning: Could not save progress file: {e}")


def is_already_downloaded(name: str) -> bool:
    """Check if a species already has a downloaded GBIF file."""
    safe_name = name.replace(" ", "_").replace("/", "_").replace(",", "_").replace("\\", "_")
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in "_-")
    gbif_file = DATA_DIR / f"gbif_{safe_name}.csv"
    return gbif_file.exists()


def get_json(url: str, params: Optional[dict] = None, tries: int = 3, verify: bool = True) -> Optional[dict]:
    """Fetch JSON from API with retries."""
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=30, verify=verify)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if i < tries - 1:
                time.sleep(2 ** i)
    return None


def gbif_match_name(name: str) -> Optional[Dict]:
    """Try to match a name in GBIF and return taxon info."""
    m = get_json("https://api.gbif.org/v1/species/match", {"name": name})
    if m and m.get("usageKey"):
        return {
            "key": str(m["usageKey"]),
            "scientific_name": m.get("scientificName"),
            "canonical_name": m.get("canonicalName"),
            "rank": m.get("rank"),
            "status": m.get("status"),
        }
    return None


def gbif_download_occurrences(taxon_key: str, species_name: str, limit: int = 500) -> pd.DataFrame:
    """Download occurrence records from GBIF for a taxon."""
    all_records = []
    offset = 0
    batch_size = 300

    while offset < limit:
        d = get_json(
            "https://api.gbif.org/v1/occurrence/search",
            {"taxonKey": taxon_key, "limit": batch_size, "offset": offset, "hasCoordinate": "true"}
        )

        if not d or not d.get("results"):
            break

        all_records.extend(d["results"])
        offset += batch_size
        time.sleep(0.1)  # Respect rate limits

        if len(d["results"]) < batch_size:
            break

    return pd.DataFrame(all_records)


def process_species(name: str, limit: int, processed: Set[str]) -> Dict:
    """Process a single species."""
    # Skip if already processed
    if name in processed:
        return {"name": name, "status": "skipped_duplicate", "reason": "Already processed"}

    # Check if file already exists (resume capability)
    if is_already_downloaded(name):
        log(f"Skipping {name}: already downloaded")
        processed.add(name)
        safe_name = name.replace(" ", "_").replace("/", "_").replace(",", "_").replace("\\", "_")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c in "_-")
        gbif_file = DATA_DIR / f"gbif_{safe_name}.csv"
        return {
            "name": name,
            "status": "skipped_existing",
            "gbif_key": None,
            "gbif_scientific_name": None,
            "occurrences": 0,
            "file": str(gbif_file),
            "reason": "File already exists"
        }

    # Skip empty or invalid names
    if not name or pd.isna(name) or str(name).strip() == "":
        return {"name": name, "status": "skipped_invalid", "reason": "Empty or NA"}

    name = str(name).strip()

    # Skip generic terms
    skip_terms = ["other", "withheld", "vertebrates", "unknown", "unidentified", "fish", "shark", "tuna"]
    if name.lower() in skip_terms:
        return {"name": name, "status": "skipped_generic", "reason": "Generic term"}

    log(f"Processing: {name}")

    result = {
        "name": name,
        "status": "failed",
        "gbif_key": None,
        "gbif_scientific_name": None,
        "occurrences": 0,
        "file": None,
        "reason": "",
    }

    # Try direct match first
    gbif_info = gbif_match_name(name)

    # If no match, try parsing common name format (e.g., "SHARK, DOGFISH, SMOOTH")
    if not gbif_info and "," in name:
        parts = [p.strip() for p in name.split(",")]
        # Try last word as species name
        if len(parts) >= 2:
            # Try combinations
            for combo in [parts[-1], f"{parts[-1]} {parts[-2]}", " ".join(reversed(parts[-2:]))]:
                gbif_info = gbif_match_name(combo)
                if gbif_info:
                    break

    if gbif_info:
        result["gbif_key"] = gbif_info["key"]
        result["gbif_scientific_name"] = gbif_info.get("scientific_name")

        # Download occurrences
        try:
            gbif_df = gbif_download_occurrences(gbif_info["key"], name, limit)
            if not gbif_df.empty:
                # Save to CSV
                safe_name = name.replace(" ", "_").replace("/", "_").replace(",", "_").replace("\\", "_")
                safe_name = "".join(c for c in safe_name if c.isalnum() or c in "_-")
                gbif_file = DATA_DIR / f"gbif_{safe_name}.csv"
                gbif_df.to_csv(gbif_file, index=False)
                result["occurrences"] = len(gbif_df)
                result["file"] = str(gbif_file)
                result["status"] = "success"
                log(f"  Success: {len(gbif_df)} occurrences saved to {gbif_file}")
            else:
                result["status"] = "no_occurrences"
                result["reason"] = "No occurrences found with coordinates"
                log(f"  No occurrences with coordinates")
        except Exception as e:
            result["status"] = "error"
            result["reason"] = str(e)
            log(f"  Error downloading: {e}")
    else:
        result["status"] = "no_match"
        result["reason"] = "No GBIF match found"
        log(f"  No GBIF match")

    processed.add(name)
    save_progress(processed)  # Save progress after each species
    time.sleep(0.5)  # Delay between species
    return result


def extract_species_from_noaa(csv_path: str) -> List[str]:
    """Extract unique species names from NOAA CSV."""
    log(f"Loading NOAA data from {csv_path}")
    df = pd.read_csv(csv_path)

    # Try different column names
    species_cols = ["species", "ts_scientific_name", "ts_afs_name"]
    species_column = None

    for col in species_cols:
        if col in df.columns:
            species_column = col
            break

    if not species_column:
        log("Error: No species column found")
        return []

    species_list = df[species_column].dropna().unique().tolist()
    log(f"Found {len(species_list)} unique species in column '{species_column}'")
    return species_list


def main():
    parser = argparse.ArgumentParser(description="Download GBIF data for all NOAA species")
    parser.add_argument(
        "--input",
        default="noaa_landings_full.csv",
        help="NOAA CSV file path (default: noaa_landings_full.csv)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max occurrences per species (default: 500)"
    )
    parser.add_argument(
        "--output-dir",
        default="external_data",
        help="Output directory (default: external_data)"
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1, recommended 1 for rate limits)"
    )

    args = parser.parse_args()

    # Update data directory
    global DATA_DIR, LOG_FILE
    DATA_DIR = Path(args.output_dir)
    DATA_DIR.mkdir(exist_ok=True)
    LOG_FILE = DATA_DIR / "download_log.txt"

    log("="*60)
    log(f"Starting GBIF download for all NOAA species")
    log(f"Input: {args.input}")
    log(f"Limit per species: {args.limit}")
    log(f"Output directory: {DATA_DIR}")
    log("="*60)

    # Extract species
    species_list = extract_species_from_noaa(args.input)
    if not species_list:
        log("No species found, exiting")
        return

    # Load existing progress (resume capability)
    processed = load_progress()
    log(f"Loaded progress: {len(processed)} species already processed")

    # Also scan for existing CSV files
    existing_files = list(DATA_DIR.glob("gbif_*.csv"))
    log(f"Found {len(existing_files)} existing GBIF files in {DATA_DIR}")

    # Process species
    results = []
    total = len(species_list)

    if args.parallel > 1:
        # Parallel processing
        log(f"Processing with {args.parallel} parallel workers")
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {
                executor.submit(process_species, name, args.limit, processed): name
                for name in species_list
            }

            for i, future in enumerate(as_completed(futures), 1):
                name = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    log(f"Progress: {i}/{total} ({i/total*100:.1f}%)")
                except Exception as e:
                    log(f"Error processing {name}: {e}")
                    results.append({"name": name, "status": "error", "reason": str(e)})
    else:
        # Sequential processing
        log("Processing sequentially")
        for i, name in enumerate(species_list, 1):
            log(f"Progress: {i}/{total} ({i/total*100:.1f}%)")
            result = process_species(name, args.limit, processed)
            results.append(result)

    # Save summary
    summary_df = pd.DataFrame(results)
    summary_file = DATA_DIR / "gbif_download_summary.csv"
    summary_df.to_csv(summary_file, index=False)

    # Print final stats
    log("="*60)
    log("DOWNLOAD COMPLETE")
    log("="*60)
    success_count = len(summary_df[summary_df["status"] == "success"])
    no_match_count = len(summary_df[summary_df["status"] == "no_match"])
    no_occurrences_count = len(summary_df[summary_df["status"] == "no_occurrences"])
    error_count = len(summary_df[summary_df["status"] == "error"])
    skipped_count = len(summary_df[summary_df["status"].str.startswith("skipped")])
    skipped_existing_count = len(summary_df[summary_df["status"] == "skipped_existing"])

    log(f"Total species: {total}")
    log(f"Successful downloads: {success_count}")
    log(f"Skipped (already exists): {skipped_existing_count}")
    log(f"No GBIF match: {no_match_count}")
    log(f"No occurrences: {no_occurrences_count}")
    log(f"Errors: {error_count}")
    log(f"Other skipped: {skipped_count - skipped_existing_count}")
    log(f"Summary saved to: {summary_file}")

    print("\n" + "="*60)
    print("DOWNLOAD COMPLETE")
    print("="*60)
    print(f"Total species: {total}")
    print(f"Successful downloads: {success_count}")
    print(f"Skipped (already exists): {skipped_existing_count}")
    print(f"No GBIF match: {no_match_count}")
    print(f"No occurrences: {no_occurrences_count}")
    print(f"Errors: {error_count}")
    print(f"Other skipped: {skipped_count - skipped_existing_count}")
    print(f"Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
