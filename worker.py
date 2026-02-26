"""
worker.py — Celery background worker for processing YouTube channel jobs.
Processes channels sequentially (one at a time) to stay within free tier RAM limits.
Stores job progress in Redis for real-time status polling.
"""

import os
import ssl
import uuid
import shutil
import logging
from datetime import datetime

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded
from dotenv import load_dotenv

from screenshot_capture import capture_channel_screenshot
from pdf_generator import generate_pdf

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Redis connection
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Initialize Celery
celery_app = Celery(
    'yt_lead_gen',
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    broker_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE},
    redis_backend_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE},
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=5,
    broker_connection_retry_on_startup=True,
)

# Directories
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'screenshots')
PDF_DIR = os.path.join(os.path.dirname(__file__), 'pdfs')


def _get_redis_client():
    """Get a Redis client from the Celery broker connection."""
    import redis
    return redis.from_url(REDIS_URL, decode_responses=True)


def _update_job_status(job_id: str, status: str, progress: int = 0,
                       total: int = 0, download_url: str = '', error: str = ''):
    """Update job status in Redis."""
    r = _get_redis_client()
    key = f'job:{job_id}'
    r.hset(key, mapping={
        'status': status,
        'progress': str(progress),
        'total': str(total),
        'download_url': download_url,
        'error': error,
    })
    r.expire(key, 1800)


@celery_app.task(
    name='process_job',
    bind=True,
    soft_time_limit=840,
    time_limit=900,
    max_retries=0,
)
def process_job(self, job_id: str, channels: list[str]):
    """
    Process a YouTube lead generation job.

    1. For each channel: capture screenshot + extract channel name
    2. When all done: generate PDF with channel names as headers
    3. Update job status to 'complete' with download URL
    """
    total = len(channels)
    job_screenshots_dir = os.path.join(SCREENSHOTS_DIR, job_id)
    os.makedirs(job_screenshots_dir, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    _update_job_status(job_id, 'processing', progress=0, total=total)

    # Collect entries: {path, channel_name}
    pdf_entries = []

    try:
        for i, channel_url in enumerate(channels):
            logger.info(f"[{job_id}] Processing channel {i + 1}/{total}: {channel_url}")
            _update_job_status(job_id, 'processing', progress=i, total=total)

            screenshot_filename = f"channel_{i + 1:03d}.png"
            screenshot_path = os.path.join(job_screenshots_dir, screenshot_filename)

            result = capture_channel_screenshot(channel_url, screenshot_path)

            if result:
                pdf_entries.append(result)
                logger.info(f"[{job_id}] Channel {i + 1}/{total} captured: {result['channel_name']}")
            else:
                logger.warning(f"[{job_id}] Channel {i + 1}/{total} failed — skipping")

        if not pdf_entries:
            _update_job_status(
                job_id, 'failed', progress=total, total=total,
                error='Failed to capture any channel screenshots. Please check the URLs.'
            )
            return

        logger.info(f"[{job_id}] Generating PDF from {len(pdf_entries)} screenshots...")
        _update_job_status(job_id, 'generating_pdf', progress=total, total=total)

        pdf_filename = f"{job_id}.pdf"
        pdf_path = os.path.join(PDF_DIR, pdf_filename)

        generate_pdf(pdf_entries, pdf_path)

        download_url = f"/api/download/{job_id}"
        _update_job_status(
            job_id, 'complete', progress=total, total=total,
            download_url=download_url
        )

        logger.info(f"[{job_id}] Job complete! PDF: {pdf_filename}")

    except SoftTimeLimitExceeded:
        logger.error(f"[{job_id}] Job timed out (15 minute limit)")
        _update_job_status(
            job_id, 'failed', progress=0, total=total,
            error='Job timed out. Try fewer channels.'
        )

    except Exception as e:
        logger.error(f"[{job_id}] Job failed: {str(e)}")
        _update_job_status(
            job_id, 'failed', progress=0, total=total,
            error=f'An error occurred: {str(e)}'
        )

    finally:
        try:
            if os.path.exists(job_screenshots_dir):
                shutil.rmtree(job_screenshots_dir)
                logger.info(f"[{job_id}] Cleaned up screenshots")
        except Exception:
            pass
