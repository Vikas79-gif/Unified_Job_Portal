#!/usr/bin/env python3
"""Screenshot capture script for Unified Job Portal"""
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

# Configuration
BASE_URL = "http://127.0.0.1:5000"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots")
SCREENSHOTS = [
    {"url": "/", "name": "homepage.png"},
    {"url": "/dashboard", "name": "dashboard.png"},
    {"url": "/admin/login", "name": "admin.png"},
    {"url": "/jobs", "name": "jobs.png"},
    {"url": "/apply/1", "name": "apply.png"},
]

def take_screenshots():
    """Take screenshots of all configured pages"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        print(f"Capturing screenshots from {BASE_URL}...")
        print("=" * 50)

        for screenshot in SCREENSHOTS:
            url = f"{BASE_URL}{screenshot['url']}"
            filename = screenshot['name']

            try:
                print(f"  Capturing {filename}...")
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(500)
                page.screenshot(path=os.path.join(OUTPUT_DIR, filename), full_page=True)
                print(f"     Saved: {filename}")

            except Exception as e:
                print(f"     Error: {e}")

        browser.close()

    print("=" * 50)
    print(f"Screenshots saved to: {os.path.abspath(OUTPUT_DIR)}")
    return OUTPUT_DIR

if __name__ == "__main__":
    take_screenshots()
