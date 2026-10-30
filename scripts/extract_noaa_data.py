#!/usr/bin/env python3
"""
Extract data from NOAA FOSS (Fisheries One Stop Shop) website.

This script attempts to extract all data from the NOAA FOSS application
at https://apps-st.fisheries.noaa.gov/foss/

Usage:
    python scripts/extract_noaa_data.py --output noaa_data.csv
"""
import argparse
import time
import csv
from typing import Optional
import requests
from bs4 import BeautifulSoup


def extract_noaa_data(
    base_url: str = "https://apps-st.fisheries.noaa.gov/foss/f",
    page_id: str = "215:7",
    output_file: str = "noaa_data.csv",
    max_rows: Optional[int] = None,
    delay: float = 1.0,
) -> None:
    """
    Extract data from NOAA FOSS application.

    Args:
        base_url: Base URL for the FOSS application
        page_id: Page ID to extract from (format: app_id:page_id)
        output_file: Path to save the CSV output
        max_rows: Maximum number of rows to extract (None for all)
        delay: Delay between requests in seconds
    """
    session = requests.Session()

    # Set headers to mimic a real browser
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })

    print(f"Attempting to access NOAA FOSS at {base_url}?p={page_id}...")

    try:
        # Try to access the page
        response = session.get(f"{base_url}?p={page_id}", timeout=30)
        print(f"Response status: {response.status_code}")

        if response.status_code == 403:
            print("\n" + "="*70)
            print("ERROR: Access denied (403 Forbidden)")
            print("="*70)
            print("\nThe NOAA FOSS website is blocking automated access.")
            print("This is common for government data portals.")
            print("\nPossible solutions:")
            print("1. Check if there's an official API or data download option")
            print("2. Look for a public dataset URL or CSV export")
            print("3. Contact NOAA for data access")
            print("4. Try manually downloading from the browser")
            print("\nLet me try to find alternative access methods...")
            return try_alternative_access(session, base_url, page_id, output_file)

        elif response.status_code == 200:
            print("Successfully accessed the page!")
            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for data tables
            tables = soup.find_all('table')
            print(f"Found {len(tables)} tables on the page")

            if tables:
                return extract_from_tables(tables, output_file, max_rows)
            else:
                print("No tables found. The page might require JavaScript or login.")
                print("Consider using a browser automation tool like Playwright or Selenium.")

        else:
            print(f"Unexpected status code: {response.status_code}")

    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")


def try_alternative_access(
    session: requests.Session,
    base_url: str,
    page_id: str,
    output_file: str,
) -> None:
    """Try alternative methods to access the data."""
    print("\n" + "="*70)
    print("Trying alternative access methods...")
    print("="*70)

    # Try adding common parameters for CSV export
    export_patterns = [
        f"{base_url}?p={page_id}&FLOW_EXCEL_OUTPUT=1",
        f"{base_url}?p={page_id}&FLOW_FILE_OUTPUT=1",
        f"{base_url}?p={page_id}&FORMAT=CSV",
        f"{base_url}?p={page_id}&OUTPUT=CSV",
    ]

    for url in export_patterns:
        print(f"\nTrying: {url}")
        try:
            response = session.get(url, timeout=30)
            print(f"Status: {response.status_code}")

            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                print(f"Content-Type: {content_type}")

                if 'csv' in content_type or 'excel' in content_type or 'spreadsheet' in content_type:
                    print("Found CSV/Excel data! Saving...")
                    with open(output_file, 'wb') as f:
                        f.write(response.content)
                    print(f"Data saved to {output_file}")
                    return
                elif 'text/html' in content_type:
                    # Check if it's a CSV file served as HTML
                    if response.text.startswith(',') or response.text.count(',') > 10:
                        print("Content looks like CSV, saving...")
                        with open(output_file, 'w', newline='', encoding='utf-8') as f:
                            f.write(response.text)
                        print(f"Data saved to {output_file}")
                        return

        except Exception as e:
            print(f"Error: {e}")

    print("\n" + "="*70)
    print("Alternative methods failed.")
    print("="*70)
    print("\nRecommendation: Use Playwright or Selenium for browser automation")
    print("These tools can handle JavaScript-rendered content and interactive elements.")


def extract_from_tables(tables, output_file: str, max_rows: Optional[int]) -> None:
    """Extract data from HTML tables and save to CSV."""
    print(f"\nExtracting data from {len(tables)} table(s)...")

    all_data = []
    for i, table in enumerate(tables):
        rows = table.find_all('tr')
        print(f"Table {i+1}: Found {len(rows)} rows")

        for row in rows:
            cells = row.find_all(['td', 'th'])
            row_data = [cell.get_text(strip=True) for cell in cells]
            if row_data:  # Skip empty rows
                all_data.append(row_data)

            if max_rows and len(all_data) >= max_rows:
                break

        if max_rows and len(all_data) >= max_rows:
            break

    if all_data:
        print(f"Extracted {len(all_data)} rows")
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(all_data)
        print(f"Data saved to {output_file}")
    else:
        print("No data extracted from tables.")


def main():
    parser = argparse.ArgumentParser(description="Extract data from NOAA FOSS")
    parser.add_argument(
        "--output",
        default="noaa_data.csv",
        help="Output CSV file path (default: noaa_data.csv)"
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Maximum number of rows to extract (default: all)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between requests in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--url",
        default="215:7",
        help="Page ID to extract (format: app_id:page_id, default: 215:7)"
    )

    args = parser.parse_args()

    extract_noaa_data(
        page_id=args.url,
        output_file=args.output,
        max_rows=args.max_rows,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
