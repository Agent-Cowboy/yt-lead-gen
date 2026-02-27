"""
worker.py — Job processing functions for YT Lead Gen.
Contains the core screenshot + PDF pipeline as plain Python functions.
No Celery — jobs run in background threads from main.py.
"""

import os
import shutil
import logging

from screenshot_capture import capture_channel_screenshot
from pdf_generator import generate_pdf

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Directories
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'screenshots')
PDF_DIR = os.path.join(os.path.dirname(__file__), 'pdfs')


def process_job(job_id: str, channels: list[str], set_job_fn):
    """
    Process a YouTube lead generation job.

    1. For each channel: capture screenshot + extract channel name
    2. When all done: generate PDF with channel names as headers
    3. Update job status via set_job_fn callback

    Args:
        job_id: Unique job identifier
        channels: List of YouTube channel URLs
        set_job_fn: Callback function to update job status
    """
    total = len(channels)
    job_screenshots_dir = os.path.join(SCREENSHOTS_DIR, job_id)
    os.makedirs(job_screenshots_dir, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    set_job_fn(job_id, {
        'status': 'processing', 'progress': '0', 'total': str(total),
        'download_url': '', 'error': '',
    })

    pdf_entries = []

    try:
        for i, channel_url in enumerate(channels):
            logger.info(f"[{job_id}] Processing channel {i + 1}/{total}")
            set_job_fn(job_id, {
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
            set_job_fn(job_id, {
                'status': 'failed', 'progress': str(total), 'total': str(total),
                'download_url': '',
                'error': 'Failed to capture any screenshots. Check the URLs.',
            })
            return

        logger.info(f"[{job_id}] Generating PDF from {len(pdf_entries)} screenshots")
        set_job_fn(job_id, {
            'status': 'generating_pdf', 'progress': str(total),
            'total': str(total), 'download_url': '', 'error': '',
        })

        pdf_path = os.path.join(PDF_DIR, f"{job_id}.pdf")
        generate_pdf(pdf_entries, pdf_path)

        set_job_fn(job_id, {
            'status': 'complete', 'progress': str(total), 'total': str(total),
            'download_url': f"/api/download/{job_id}", 'error': '',
        })
        logger.info(f"[{job_id}] Job complete!")

    except Exception as e:
        logger.error(f"[{job_id}] Job failed: {type(e).__name__}")
        set_job_fn(job_id, {
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
