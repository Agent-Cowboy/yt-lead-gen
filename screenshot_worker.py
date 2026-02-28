"""
screenshot_worker.py — Standalone Playwright script run as a subprocess.
Called by screenshot_capture.py to avoid the asyncio loop conflict.

Usage: python -m screenshot_worker <channel_url> <output_path>
Outputs JSON to stdout on success: {"path": "...", "channel_name": "..."}
Exit code 0 = success, non-zero = failure (error details on stderr).
"""

import os
import re
import sys
import json
import time
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

# Browser launch arguments for Linux + speed
BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--disable-software-rasterizer',
    '--disable-extensions',
    '--no-zygote',
    '--single-process',
    '--lang=en-US',
    '--disable-background-networking',
    '--disable-default-apps',
    '--disable-sync',
    '--no-first-run',
    '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--memory-pressure-off',
    '--disable-features=TranslateUI',
    '--disable-ipc-flooding-protection',
]

# Screenshot dimensions
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 3000

# Scrolling config
SCROLL_COUNT = 12
SCROLL_DELAY_MS = 20


def capture(channel_url: str, output_path: str) -> dict:
    """Run the actual Playwright capture. Returns result dict or raises."""
    videos_url = channel_url.rstrip('/') + '/videos'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with sync_playwright() as p:
        logger.info(f"Launching browser for: {videos_url}")
        browser = p.chromium.launch(
            headless=True,
            args=BROWSER_ARGS,
        )

        try:
            context = browser.new_context(
                viewport={'width': VIEWPORT_WIDTH, 'height': VIEWPORT_HEIGHT},
                locale='en-US',
                timezone_id='America/New_York',
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/121.0.0.0 Safari/537.36'
                ),
            )

            # Set a hard timeout for ALL operations on this page
            context.set_default_timeout(15000)

            page = context.new_page()

            # Navigate — use 'domcontentloaded' because YouTube NEVER reaches
            # 'networkidle' (constant analytics/ads/websocket traffic)
            logger.info(f"Navigating to: {videos_url}")
            page.goto(videos_url, wait_until='domcontentloaded', timeout=30000)

            # Wait for page content to render
            page.wait_for_timeout(3000)

            # Dismiss cookie/consent banners if present
            try:
                consent_button = page.locator(
                    'button:has-text("Accept all"), '
                    'button:has-text("Reject all"), '
                    'button[aria-label="Accept all"]'
                )
                if consent_button.count() > 0:
                    consent_button.first.click(timeout=2000)
                    page.wait_for_timeout(500)
            except Exception:
                pass

            # Extract channel name
            channel_name = _extract_channel_name(page, channel_url)

            # Scroll down to load more video thumbnails
            for _ in range(SCROLL_COUNT):
                page.evaluate('window.scrollBy(0, window.innerHeight)')
                page.wait_for_timeout(SCROLL_DELAY_MS)

            # Scroll back to top for the final screenshot
            page.evaluate('window.scrollTo(0, 0)')
            time.sleep(1.2)

            # Capture screenshot with clip for better video visibility
            page.screenshot(
                path=output_path,
                clip={'x': 0, 'y': 0, 'width': 1280, 'height': 2800},
            )

            logger.info(f"Screenshot saved (channel: {channel_name})")

            context.close()
            return {
                'path': output_path,
                'channel_name': channel_name,
            }

        finally:
            browser.close()


def _extract_channel_name(page, channel_url: str) -> str:
    """Extract the channel display name from the page."""
    # Try page title first — fastest and most reliable
    try:
        title = page.title()
        if title and ' - YouTube' in title:
            name = title.replace(' - YouTube', '').strip()
            if name:
                return name
    except Exception:
        pass

    # Try a couple of common selectors with SHORT timeouts
    selectors = [
        '#channel-name yt-formatted-string',
        'yt-formatted-string.ytd-channel-name',
    ]

    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=1500):
                name = el.inner_text(timeout=1500).strip()
                if name:
                    return name
        except Exception:
            continue

    # Last resort: extract @handle from URL
    return _handle_from_url(channel_url)


def _handle_from_url(url: str) -> str:
    """Extract a readable name from a YouTube channel URL."""
    match = re.search(r'@([\w.-]+)', url)
    if match:
        return f"@{match.group(1)}"

    match = re.search(r'/(c|user|channel)/([\w.-]+)', url)
    if match:
        return match.group(2)

    return "Unknown Channel"


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python -m screenshot_worker <channel_url> <output_path>",
              file=sys.stderr)
        sys.exit(1)

    channel_url = sys.argv[1]
    output_path = sys.argv[2]

    try:
        result = capture(channel_url, output_path)
        # Output JSON to stdout for the parent process to read
        print(json.dumps(result))
        sys.exit(0)
    except PlaywrightTimeout:
        logger.error(f"Timeout loading channel: {channel_url}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error capturing channel: {type(e).__name__}: {e}")
        sys.exit(1)
