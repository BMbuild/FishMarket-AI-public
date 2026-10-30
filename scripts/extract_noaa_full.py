#!/usr/bin/env python3
"""
Extract ALL data from NOAA ODS (Open Data Service) endpoint with pagination.

This script fetches all records from the NOAA landings API using pagination
and saves them to a CSV file.

Usage:
    python scripts/extract_noaa_full.py --output noaa_landings_full.csv
"""
import argparse
import requests
import pandas as pd
import json
import time
from typing import Optional


def extract_noaa_full(
    base_url: str = "https://apps-st.fisheries.noaa.gov/ods/foss/landings/",
    output_file: str = "noaa_landings_full.csv",
    batch_size: int = 1000,
    delay: float = 0.5,
) -> None:
    """
    Extract all data from NOAA ODS endpoint with pagination.

    Args:
        base_url: Base URL for the ODS endpoint
        output_file: Path to save the CSV output
        batch_size: Number of records per request
        delay: Delay between requests in seconds
    """
    session = requests.Session()

    # Set headers
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
    })

    print(f"Extracting all data from {base_url}")
    print(f"Batch size: {batch_size}")
    print(f"Output file: {output_file}")
    print()

    all_items = []
    current_url = f"{base_url}?limit={batch_size}"
    page_num = 0

    while current_url:
        page_num += 1
        print(f"Fetching page {page_num}... ", end='', flush=True)

        try:
            response = session.get(current_url, timeout=60)
            response.raise_for_status()

            data = response.json()

            # NOAA ODS format: {"items": [...], "hasMore": bool, "links": [...]}
            items = data.get('items', [])
            has_more = data.get('hasMore', False)

            if not items:
                print("No more records")
                break

            all_items.extend(items)
            print(f"Got {len(items)} records (total so far: {len(all_items)})")

            # Find the next link
            current_url = None
            if has_more:
                links = data.get('links', [])
                for link in links:
                    if link.get('rel') == 'next':
                        current_url = link.get('href')
                        break

            if not current_url and has_more:
                # Fallback: construct next URL manually
                offset = data.get('offset', 0) + len(items)
                current_url = f"{base_url}?limit={batch_size}&offset={offset}"

            if not current_url:
                print("Reached end of data")
                break

            # Small delay to be respectful
            time.sleep(delay)

        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            break

    print(f"\nTotal records extracted: {len(all_items)}")

    if all_items:
        # Convert to DataFrame
        df = pd.DataFrame(all_items)

        # Remove the 'links' column if present (it's just metadata)
        if 'links' in df.columns:
            df = df.drop(columns=['links'])

        # Save to CSV
        df.to_csv(output_file, index=False)
        print(f"Saved to {output_file}")
        print(f"Columns: {list(df.columns)}")
        print(f"Shape: {df.shape}")
    else:
        print("No data extracted")


def main():
    parser = argparse.ArgumentParser(description="Extract all NOAA ODS data with pagination")
    parser.add_argument(
        "--output",
        default="noaa_landings_full.csv",
        help="Output CSV file path (default: noaa_landings_full.csv)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Records per request (default: 1000)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between requests in seconds (default: 0.5)"
    )
    parser.add_argument(
        "--url",
        default="https://apps-st.fisheries.noaa.gov/ods/foss/landings/",
        help="ODS endpoint URL"
    )

    args = parser.parse_args()

    extract_noaa_full(
        base_url=args.url,
        output_file=args.output,
        batch_size=args.batch_size,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
