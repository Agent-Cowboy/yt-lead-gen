"""
screenshot_capture.py — Playwright browser automation.
Launches headless Chromium, navigates to a YouTube channel's /videos page,
scrolls to load content, captures a screenshot, and extracts the channel name.
"""

import os
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# Browser launch arguments for Linux without system deps + speed
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
]

# Screenshot dimensions
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 2400

# Scrolling config
SCROLL_COUNT = 8
SCROLL_DELAY_MS = 20


def capture_channel_screenshot(channel_url: str, output_path: str) -> dict | None:
    """
    Navigate to a YouTube channel's /videos page, capture a screenshot,
    and extract the channel name.

    Args:
        channel_url: Full YouTube channel URL (e.g., https://www.youtube.com/@mkbhd)
        output_path: File path to save the screenshot PNG

    Returns:
        Dict with 'path' and 'channel_name' on success, None on failure
    """
    # Ensure the channel URL points to the /videos tab
    videos_url = channel_url.rstrip('/') + '/videos'

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=BROWSER_ARGS,
            )

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

            page = context.new_page()

            # Navigate to the videos page
            logger.info(f"Navigating to: {videos_url}")
            page.goto(videos_url, wait_until='networkidle', timeout=25000)

            # Dismiss cookie/consent banners if present
            try:
                consent_button = page.locator(
                    'button:has-text("Accept all"), '
                    'button:has-text("Reject all"), '
                    'button[aria-label="Accept all"]'
                )
                if consent_button.count() > 0:
                    consent_button.first.click(timeout=3000)
                    page.wait_for_timeout(1000)
            except Exception:
                pass  # No consent dialog — continue

            # Extract channel name from the page
            channel_name = _extract_channel_name(page, channel_url)

            # Scroll down to load more video thumbnails
            for _ in range(SCROLL_COUNT):
                page.evaluate('window.scrollBy(0, window.innerHeight)')
                page.wait_for_timeout(SCROLL_DELAY_MS)

            # Scroll back to top for the final screenshot
            page.evaluate('window.scrollTo(0, 0)')
            page.wait_for_timeout(500)

            # Capture screenshot
            page.screenshot(
                path=output_path,
                full_page=False,
                type='png',
            )

            logger.info(f"Screenshot saved (channel: {channel_name})")

            context.close()
            browser.close()

            return {
                'path': output_path,
                'channel_name': channel_name,
            }

    except PlaywrightTimeout:
        logger.error(f"Timeout loading channel: {channel_url}")
        return None
    except Exception as e:
        logger.error(f"Error capturing channel: {type(e).__name__}")
        return None


def _extract_channel_name(page, channel_url: str) -> str:
    """
    Try to extract the channel display name from the page.
    Falls back to the @handle from the URL if extraction fails.
    """
    # Try common YouTube selectors for the channel name
    selectors = [
        'yt-formatted-string.ytd-channel-name',
        '#channel-name yt-formatted-string',
        '#text.ytd-channel-name',
        'ytd-channel-name #text',
        '#channel-header ytd-channel-name',
    ]

    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=2000):
                name = el.inner_text(timeout=2000).strip()
                if name and len(name) > 0:
                    return name
        except Exception:
            continue

    # Fallback: try page title (usually "ChannelName - YouTube")
    try:
        title = page.title()
        if title and ' - YouTube' in title:
            return title.replace(' - YouTube', '').strip()
    except Exception:
        pass

    # Last resort: extract @handle from URL
    return _handle_from_url(channel_url)


def _handle_from_url(url: str) -> str:
    """Extract a readable name from a YouTube channel URL."""
    import re
    match = re.search(r'@([\w.-]+)', url)
    if match:
        return f"@{match.group(1)}"

    match = re.search(r'/(c|user|channel)/([\w.-]+)', url)
    if match:
        return match.group(2)

    return "Unknown Channel"
