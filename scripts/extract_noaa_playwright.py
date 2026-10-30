#!/usr/bin/env python3
"""
Extract data from NOAA FOSS using Playwright browser automation.

This script uses Playwright to interact with the NOAA FOSS web application
and extract all data by scrolling through pagination or using export features.

Usage:
    python scripts/extract_noaa_playwright.py --output noaa_data.csv

Requirements:
    pip install playwright
    playwright install
"""
import argparse
import asyncio
import csv
from typing import Optional
from playwright.async_api import async_playwright, Page, Browser


async def extract_noaa_data_playwright(
    url: str = "https://apps-st.fisheries.noaa.gov/foss/f?p=215:7:14486603183345",
    output_file: str = "noaa_data.csv",
    headless: bool = True,
    max_rows: Optional[int] = None,
    timeout: int = 60000,
) -> None:
    """
    Extract data from NOAA FOSS using Playwright.

    Args:
        url: Full URL to the FOSS page
        output_file: Path to save the CSV output
        headless: Run browser in headless mode
        max_rows: Maximum number of rows to extract (None for all)
        timeout: Page load timeout in milliseconds
    """
    print(f"Starting Playwright extraction from {url}")
    print(f"Output file: {output_file}")
    print(f"Headless mode: {headless}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        try:
            print("Navigating to page...")
            await page.goto(url, timeout=timeout, wait_until="networkidle")

            # Wait for page to load
            await asyncio.sleep(3)

            # Take a screenshot for debugging
            await page.screenshot(path="noaa_page.png", full_page=True)
            print("Screenshot saved to noaa_page.png")

            # Try different extraction strategies
            success = await try_export_button(page, output_file)
            if success:
                print("Successfully extracted data via export button")
                return

            success = await try_table_extraction(page, output_file, max_rows)
            if success:
                print("Successfully extracted data from tables")
                return

            success = await try_pagination_extraction(page, output_file, max_rows)
            if success:
                print("Successfully extracted data via pagination")
                return

            print("\n" + "="*70)
            print("Extraction failed. Manual intervention may be required.")
            print("="*70)
            print("\nTips:")
            print("1. Run with --no-headless to see the browser")
            print("2. Check noaa_page.png to see what loaded")
            print("3. The site may require login or authentication")
            print("4. Look for official data download options")

        except Exception as e:
            print(f"Error during extraction: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


async def try_export_button(page: Page, output_file: str) -> bool:
    """Try to find and click an export/download button."""
    print("\nLooking for export/download buttons...")

    # Common button text patterns
    export_patterns = [
        "Export",
        "Download",
        "CSV",
        "Excel",
        "Save",
        "export",
        "download",
        "csv",
        "excel",
    ]

    for pattern in export_patterns:
        try:
            button = page.get_by_role("button", name=pattern, exact=False)
            if await button.is_visible():
                print(f"Found button with text: {pattern}")
                await button.click()
                await asyncio.sleep(2)

                # Check for download
                download = await page.wait_for_event("download", timeout=5000)
                path = await download.path()
                print(f"Downloaded file to: {path}")

                # Copy to output location
                import shutil
                shutil.copy(path, output_file)
                print(f"Saved to: {output_file}")
                return True

        except Exception:
            continue

    print("No export button found")
    return False


async def try_table_extraction(page: Page, output_file: str, max_rows: Optional[int]) -> bool:
    """Extract data from HTML tables on the page."""
    print("\nAttempting to extract from tables...")

    try:
        tables = await page.query_selector_all("table")
        print(f"Found {len(tables)} tables")

        if not tables:
            return False

        all_data = []
        for i, table in enumerate(tables):
            rows = await table.query_selector_all("tr")
            print(f"Table {i+1}: {len(rows)} rows")

            for row in rows:
                cells = await row.query_selector_all("td, th")
                row_data = []
                for cell in cells:
                    text = await cell.inner_text()
                    row_data.append(text.strip())

                if row_data:
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
            print(f"Saved to: {output_file}")
            return True

    except Exception as e:
        print(f"Error extracting from tables: {e}")

    return False


async def try_pagination_extraction(page: Page, output_file: str, max_rows: Optional[int]) -> bool:
    """Extract data by scrolling through pagination."""
    print("\nAttempting pagination extraction...")

    try:
        # Look for pagination controls
        next_buttons = [
            page.get_by_role("button", name="Next"),
            page.get_by_role("button", name="next"),
            page.get_by_label("Next"),
            page.locator("button:has-text('Next')"),
            page.locator("a:has-text('Next')"),
        ]

        all_data = []
        page_num = 1

        while True:
            print(f"Processing page {page_num}...")

            # Extract current page
            tables = await page.query_selector_all("table")
            if tables:
                table = tables[0]  # Use first table
                rows = await table.query_selector_all("tr")

                for row in rows:
                    cells = await row.query_selector_all("td, th")
                    row_data = []
                    for cell in cells:
                        text = await cell.inner_text()
                        row_data.append(text.strip())

                    if row_data:
                        all_data.append(row_data)

                    if max_rows and len(all_data) >= max_rows:
                        break

            if max_rows and len(all_data) >= max_rows:
                break

            # Try to click next
            clicked = False
            for btn in next_buttons:
                try:
                    if await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(2)
                        clicked = True
                        page_num += 1
                        break
                except Exception:
                    continue

            if not clicked:
                print("No more pages or pagination not found")
                break

            if page_num > 1000:  # Safety limit
                print("Reached page limit (1000)")
                break

        if all_data:
            print(f"Extracted {len(all_data)} rows from {page_num} pages")
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(all_data)
            print(f"Saved to: {output_file}")
            return True

    except Exception as e:
        print(f"Error during pagination: {e}")

    return False


def main():
    parser = argparse.ArgumentParser(description="Extract NOAA FOSS data using Playwright")
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
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run browser in headless mode (default: True)"
    )
    parser.add_argument(
        "--url",
        default="https://apps-st.fisheries.noaa.gov/foss/f?p=215:7:14486603183345",
        help="Full URL to extract from"
    )

    args = parser.parse_args()

    asyncio.run(extract_noaa_data_playwright(
        url=args.url,
        output_file=args.output,
        headless=args.headless,
        max_rows=args.max_rows,
    ))


if __name__ == "__main__":
    main()
