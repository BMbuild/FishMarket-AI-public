#!/usr/bin/env python3
"""
Extract data from NOAA ODS (Open Data Service) endpoint.

This script attempts to extract data from NOAA's ODS API/endpoint.

Usage:
    python scripts/extract_noaa_ods.py --output noaa_data.csv
"""
import argparse
import requests
import pandas as pd
from typing import Optional


def extract_noaa_ods(
    base_url: str = "https://apps-st.fisheries.noaa.gov/ods/foss/landings/",
    output_file: str = "noaa_landings.csv",
    format: str = "json",
) -> None:
    """
    Extract data from NOAA ODS endpoint.

    Args:
        base_url: Base URL for the ODS endpoint
        output_file: Path to save the CSV output
        format: Output format (json, csv)
    """
    session = requests.Session()

    # Set headers to mimic a real browser
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/csv, */*',
        'Accept-Language': 'en-US,en;q=0.5',
    })

    print(f"Attempting to access NOAA ODS at {base_url}...")

    # Try different URL patterns for ODS/API endpoints
    url_patterns = [
        base_url,
        f"{base_url}?format=json",
        f"{base_url}?format=csv",
        f"{base_url}?$format=json",
        f"{base_url}?$format=csv",
        f"{base_url}.json",
        f"{base_url}.csv",
        f"{base_url}api/",
        f"{base_url}data/",
    ]

    for url in url_patterns:
        print(f"\nTrying: {url}")
        try:
            response = session.get(url, timeout=30)
            print(f"Status: {response.status_code}")
            print(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")

            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '').lower()

                # If it's JSON
                if 'json' in content_type or url.endswith('.json'):
                    print("Found JSON data!")
                    try:
                        data = response.json()
                        df = pd.DataFrame(data)
                        df.to_csv(output_file, index=False)
                        print(f"Saved {len(df)} rows to {output_file}")
                        return
                    except Exception as e:
                        print(f"Error parsing JSON: {e}")

                # If it's CSV
                elif 'csv' in content_type or url.endswith('.csv'):
                    print("Found CSV data!")
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(response.text)
                    print(f"Saved to {output_file}")
                    return

                # If it's HTML, might have embedded data
                elif 'html' in content_type:
                    print("Got HTML response - checking for data...")
                    # Save HTML for inspection
                    with open('noaa_response.html', 'w', encoding='utf-8') as f:
                        f.write(response.text)
                    print("Saved HTML to noaa_response.html for inspection")

                    # Try to parse as CSV anyway
                    if ',' in response.text and response.text.count(',') > 10:
                        print("Content looks like CSV, attempting to save...")
                        with open(output_file, 'w', encoding='utf-8') as f:
                            f.write(response.text)
                        print(f"Saved to {output_file}")
                        return

        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")

    print("\n" + "="*70)
    print("Could not extract data automatically.")
    print("="*70)
    print("\nRecommendations:")
    print("1. Check noaa_response.html for any data links or API endpoints")
    print("2. Look for 'Download' or 'Export' buttons in the HTML")
    print("3. Check if there's API documentation on the page")
    print("4. Try manually downloading via browser")


def main():
    parser = argparse.ArgumentParser(description="Extract NOAA ODS data")
    parser.add_argument(
        "--output",
        default="noaa_landings.csv",
        help="Output CSV file path (default: noaa_landings.csv)"
    )
    parser.add_argument(
        "--url",
        default="https://apps-st.fisheries.noaa.gov/ods/foss/landings/",
        help="ODS endpoint URL"
    )

    args = parser.parse_args()

    extract_noaa_ods(
        base_url=args.url,
        output_file=args.output,
    )


if __name__ == "__main__":
    main()
