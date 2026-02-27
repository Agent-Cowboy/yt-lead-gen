"""
screenshot_capture.py — Playwright browser automation wrapper.
Runs Playwright in a subprocess to avoid asyncio loop conflicts with FastAPI.
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

    Returns:
        Dict with 'path' and 'channel_name' on success, None on failure
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Path to the standalone Playwright script
    worker_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'screenshot_worker.py'
    )

    try:
        logger.info(f"Starting capture subprocess: {channel_url}")
        logger.info(f"Worker script: {worker_script} (exists={os.path.exists(worker_script)})")
        logger.info(f"Python: {sys.executable}")

        result = subprocess.run(
            [sys.executable, worker_script, channel_url, output_path],
            capture_output=True,
            text=True,
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )

        # Log ALL output for debugging
        if result.stdout:
            logger.info(f"Subprocess stdout: {result.stdout[:500]}")
        if result.stderr:
            logger.info(f"Subprocess stderr: {result.stderr[:500]}")

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout.strip())
                return data
            except (json.JSONDecodeError, ValueError):
                logger.error(f"Invalid JSON from subprocess: {result.stdout[:200]}")
                return None
        else:
            logger.error(
                f"Capture failed (exit {result.returncode}). "
                f"stderr: {result.stderr[:500]}"
            )
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"Capture timed out ({CAPTURE_TIMEOUT_SECONDS}s): {channel_url}")
        return None
    except Exception as e:
        logger.error(f"Subprocess error: {type(e).__name__}: {e}")
        return None
