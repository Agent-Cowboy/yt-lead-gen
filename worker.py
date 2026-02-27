"""
worker.py — Job processing functions for YT Lead Gen.
Contains the core screenshot + PDF pipeline as plain Python functions.
No Celery — jobs run in background threads from main.py.
Updates job status directly in Redis (or in-memory fallback).
"""

import os
from dotenv import load_dotenv
load_dotenv()

import ssl
import shutil
import logging
import redis as redis_lib

from screenshot_capture import capture_channel_screenshot
from pdf_generator import generate_pdf

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
REDIS_URL = os.environ.get('REDIS_URL', '')

# Directories
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'screenshots')
PDF_DIR = os.path.join(os.path.dirname(__file__), 'pdfs')


# ──────────────────────────────────────────────
# Redis connection helper
# ──────────────────────────────────────────────
def create_redis_client(url):
    """Create a Redis client with proper SSL handling for Upstash."""
    if url.startswith('rediss://'):
        return redis_lib.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3,
            ssl_cert_reqs=ssl.CERT_NONE
        )
    else:
        return redis_lib.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3
        )


# ──────────────────────────────────────────────
# Redis connection (optional — fallback to in-memory)
# ──────────────────────────────────────────────
redis_client = None
memory_jobs: dict = {}

if REDIS_URL:
    try:
        _test_client = create_redis_client(REDIS_URL)
        _test_client.ping()
        redis_client = _test_client
        logger.info("Worker: Redis connected")
    except Exception as e:
        logger.warning(f"Worker: Redis not available ({type(e).__name__}). Using in-memory store.")
else:
    logger.info("Worker: No REDIS_URL set. Using in-memory job store.")


def set_job(job_id: str, data: dict):
    """Set job data in Redis or in-memory store."""
    if redis_client:
        redis_client.hset(f"job:{job_id}", mapping=data)
        redis_client.expire(f"job:{job_id}", 1800)
    else:
        memory_jobs[job_id] = data


# ──────────────────────────────────────────────
# Main processing function
# ──────────────────────────────────────────────
def process_job_sync(job_id: str, channels: list[str]):
    """
    Process a YouTube lead generation job.

    1. For each channel: capture screenshot + extract channel name
    2. When all done: generate PDF with channel names as headers
    3. Update job status directly in Redis

    Args:
        job_id: Unique job identifier
        channels: List of YouTube channel URLs
    """
    total = len(channels)
    job_screenshots_dir = os.path.join(SCREENSHOTS_DIR, job_id)
    os.makedirs(job_screenshots_dir, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    set_job(job_id, {
        'status': 'processing', 'progress': '0', 'total': str(total),
        'download_url': '', 'error': '',
    })

    pdf_entries = []

    try:
        for i, channel_url in enumerate(channels):
            logger.info(f"[{job_id}] Processing channel {i + 1}/{total}")
            set_job(job_id, {
                'status': 'processing', 'progress': str(i), 'total': str(total),
                'download_url': '', 'error': '',
            })

            screenshot_path = os.path.join(
                job_screenshots_dir, f"channel_{i + 1:03d}.png"
            )
            result = capture_channel_screenshot(channel_url, screenshot_path)

            if result:
                pdf_entries.append(result)
                logger.info(
                    f"[{job_id}] Channel {i + 1}/{total} captured: "
                    f"{result['channel_name']}"
                )
            else:
                logger.warning(
                    f"[{job_id}] Channel {i + 1}/{total} failed — skipping"
                )

        if not pdf_entries:
            set_job(job_id, {
                'status': 'failed', 'progress': str(total), 'total': str(total),
                'download_url': '',
                'error': 'Failed to capture any screenshots. Check the URLs.',
            })
            return

        logger.info(f"[{job_id}] Generating PDF from {len(pdf_entries)} screenshots")
        set_job(job_id, {
            'status': 'generating_pdf', 'progress': str(total),
            'total': str(total), 'download_url': '', 'error': '',
        })

        pdf_path = os.path.join(PDF_DIR, f"{job_id}.pdf")
        generate_pdf(pdf_entries, pdf_path)

        set_job(job_id, {
            'status': 'complete', 'progress': str(total), 'total': str(total),
            'download_url': f"/api/download/{job_id}", 'error': '',
        })
        logger.info(f"[{job_id}] Job complete!")

    except Exception as e:
        logger.error(f"[{job_id}] Job failed: {type(e).__name__}")
        set_job(job_id, {
            'status': 'failed', 'progress': '0', 'total': str(total),
            'download_url': '', 'error': 'Processing error. Please try again.',
        })

    finally:
        try:
            if os.path.exists(job_screenshots_dir):
                shutil.rmtree(job_screenshots_dir)
                logger.info(f"[{job_id}] Cleaned up screenshots")
        except Exception:
            pass
