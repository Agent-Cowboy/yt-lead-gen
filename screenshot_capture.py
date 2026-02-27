"""
screenshot_capture.py — Playwright browser automation.
Launches headless Chromium, navigates to a YouTube channel's /videos page,
scrolls to load content, captures a screenshot, and extracts the channel name.

IMPORTANT: Uses subprocess to avoid the "Playwright Sync API inside asyncio loop"
error that occurs when running from FastAPI's threaded background tasks.
"""

import os
import sys
import json
import logging
import subprocess

logger = logging.getLogger(__name__)

# Hard timeout for the entire capture subprocess (seconds)
CAPTURE_TIMEOUT_SECONDS = 60


def capture_channel_screenshot(channel_url: str, output_path: str) -> dict | None:
    """
    Capture a screenshot by running the Playwright logic in a subprocess.
    This avoids the "Sync API inside asyncio loop" error.

    Args:
        channel_url: Full YouTube channel URL
        output_path: File path to save the screenshot PNG

    Returns:
        Dict with 'path' and 'channel_name' on success, None on failure
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Path to the standalone Playwright script
    worker_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'screenshot_worker.py'
    )

    try:
        result = subprocess.run(
            [sys.executable, worker_script, channel_url, output_path],
            capture_output=True,
            text=True,
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout.strip())
                return data
            except (json.JSONDecodeError, ValueError):
                logger.error(f"Invalid JSON output from capture subprocess: {result.stdout[:200]}")
                return None
        else:
            logger.error(f"Capture subprocess failed (exit {result.returncode}): {result.stderr[:300]}")
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"Capture subprocess timed out ({CAPTURE_TIMEOUT_SECONDS}s): {channel_url}")
        return None
    except Exception as e:
        logger.error(f"Error running capture subprocess: {type(e).__name__}: {e}")
        return None
