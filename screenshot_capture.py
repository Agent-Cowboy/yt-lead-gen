"""
screenshot_capture.py — Playwright browser automation.
Launches headless Chromium, navigates to a YouTube channel's /videos page,
scrolls to load content, captures a screenshot, and extracts the channel name.

Optimized for Render free tier (512MB RAM).
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
    '--memory-pressure-off',
    '--disable-features=TranslateUI',
    '--disable-ipc-flooding-protection',
]

# Screenshot dimensions — reduced for Render free tier (512MB RAM)
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900

# Scrolling config
SCROLL_COUNT = 5
SCROLL_DELAY_MS = 100

# Hard timeout for entire capture operation (seconds)
CAPTURE_TIMEOUT_MS = 45000


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

    browser = None
    try:
        with sync_playwright() as p:
            logger.info(f"Launching browser for: {videos_url}")
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

            # Set a hard timeout for ALL operations on this page
            context.set_default_timeout(15000)

            page = context.new_page()

            # Block unnecessary resources to save memory and speed up loading
            page.route("**/*.{png,jpg,jpeg,gif,svg,mp4,webm,woff,woff2,ttf}",
                       lambda route: route.abort())
            page.route("**/ads*", lambda route: route.abort())
            page.route("**/analytics*", lambda route: route.abort())
            page.route("**/googlesyndication*", lambda route: route.abort())
            page.route("**/doubleclick*", lambda route: route.abort())

            # Navigate — use 'domcontentloaded' because YouTube NEVER reaches
            # 'networkidle' (constant analytics/ads/websocket traffic)
            logger.info(f"Navigating to: {videos_url}")
            page.goto(videos_url, wait_until='domcontentloaded', timeout=30000)

            # Unblock images AFTER navigation so the page layout is set,
            # then wait for video thumbnails to start loading
            page.unroute_all()
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
            browser = None

            return {
                'path': output_path,
                'channel_name': channel_name,
            }

    except PlaywrightTimeout:
        logger.error(f"Timeout loading channel: {channel_url}")
        return None
    except Exception as e:
        logger.error(f"Error capturing channel {channel_url}: {type(e).__name__}: {e}")
        return None
    finally:
        # Ensure browser is always closed even on unexpected errors
        if browser:
            try:
                browser.close()
            except Exception:
                pass


def _extract_channel_name(page, channel_url: str) -> str:
    """
    Try to extract the channel display name from the page.
    Falls back to the @handle from the URL if extraction fails.
    Uses short timeouts to avoid hanging.
    """
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
    import re
    match = re.search(r'@([\w.-]+)', url)
    if match:
        return f"@{match.group(1)}"

    match = re.search(r'/(c|user|channel)/([\w.-]+)', url)
    if match:
        return match.group(2)

    return "Unknown Channel"
