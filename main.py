"""
main.py — FastAPI application with all API endpoints, security middleware,
rate limiting, GZip compression, and static file serving for the YT Lead Gen app.

Jobs always run in background threads. Redis is used for job status tracking
only (optional — falls back to in-memory if not available).
"""

import os
from dotenv import load_dotenv
load_dotenv()

import re
import ssl
import uuid
import asyncio
import logging
import threading
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import redis as redis_lib

from url_extractor import extract_channels

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
REDIS_URL = os.environ.get('REDIS_URL', '')
ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', '')
SECRET_KEY = os.environ.get('SECRET_KEY', '')
MAX_CHANNELS = int(os.environ.get('MAX_CHANNELS', '30'))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
PDF_DIR = os.path.join(BASE_DIR, 'pdfs')
SCREENSHOTS_DIR = os.path.join(BASE_DIR, 'screenshots')
PDF_EXPIRY_SECONDS = 600  # 10 minutes
MAX_REQUEST_BODY_BYTES = 50_000  # 50 KB max request body
UUID_REGEX = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

# ──────────────────────────────────────────────
# Startup check — SECRET_KEY must be set
# ──────────────────────────────────────────────
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set!")


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

# In-memory job store (fallback when Redis is not available)
memory_jobs: dict = {}

if REDIS_URL:
    try:
        _test_client = create_redis_client(REDIS_URL)
        _test_client.ping()
        redis_client = _test_client
        logger.info("Redis connected — using for job status tracking")
    except Exception as e:
        logger.warning(f"Redis not available ({type(e).__name__}). Using in-memory store.")
else:
    logger.info("No REDIS_URL set. Using in-memory job store.")


def _validate_uuid(job_id: str) -> None:
    """Validate that a job_id is a proper UUID format."""
    if not UUID_REGEX.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")


def get_job(job_id: str) -> dict | None:
    """Get job data from Redis or in-memory store."""
    if redis_client:
        data = redis_client.hgetall(f"job:{job_id}")
        return data if data else None
    return memory_jobs.get(job_id)


def set_job(job_id: str, data: dict):
    """Set job data in Redis or in-memory store."""
    if redis_client:
        redis_client.hset(f"job:{job_id}", mapping=data)
        redis_client.expire(f"job:{job_id}", 1800)
    else:
        memory_jobs[job_id] = data


def _serve_static_page(filename: str) -> HTMLResponse:
    """Read and serve an HTML file from the static directory."""
    filepath = os.path.join(STATIC_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Page not found")
    with open(filepath, 'r', encoding='utf-8') as f:
        return HTMLResponse(content=f.read())


# ──────────────────────────────────────────────
# Background job runner (threading — no Celery)
# ──────────────────────────────────────────────
def _run_job_in_thread(job_id: str, channels: list[str]):
    """Start a job in a background thread."""
    from worker import process_job_sync
    threading.Thread(
        target=process_job_sync,
        args=(job_id, channels, set_job),
        daemon=True,
    ).start()
    logger.info(f"Job {job_id} started ({len(channels)} channels)")


# ──────────────────────────────────────────────
# Scheduled cleanup tasks
# ──────────────────────────────────────────────
async def cleanup_expired_pdfs():
    """Periodically delete PDF files older than PDF_EXPIRY_SECONDS."""
    while True:
        try:
            if os.path.exists(PDF_DIR):
                now = datetime.now(timezone.utc)
                for filename in os.listdir(PDF_DIR):
                    filepath = os.path.join(PDF_DIR, filename)
                    if os.path.isfile(filepath):
                        mod_time = datetime.fromtimestamp(
                            os.path.getmtime(filepath), tz=timezone.utc
                        )
                        age = (now - mod_time).total_seconds()
                        if age > PDF_EXPIRY_SECONDS:
                            os.remove(filepath)
                            logger.info(f"Deleted expired PDF: {filename}")
        except Exception as e:
            logger.error(f"PDF cleanup error: {type(e).__name__}")
        await asyncio.sleep(60)


async def cleanup_memory_jobs():
    """Remove old entries from memory_jobs to prevent memory leaks."""
    while True:
        try:
            if not redis_client and len(memory_jobs) > 100:
                keys = list(memory_jobs.keys())
                for key in keys[:len(keys) - 50]:
                    del memory_jobs[key]
        except Exception:
            pass
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: start/stop background tasks."""
    os.makedirs(PDF_DIR, exist_ok=True)
    pdf_task = asyncio.create_task(cleanup_expired_pdfs())
    mem_task = asyncio.create_task(cleanup_memory_jobs())
    yield
    pdf_task.cancel()
    mem_task.cancel()
    try:
        await pdf_task
    except asyncio.CancelledError:
        pass
    try:
        await mem_task
    except asyncio.CancelledError:
        pass


# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────
app = FastAPI(
    title="YT Lead Gen",
    description="YouTube Lead Generator — Screenshots to PDF",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# GZip compression for responses > 500 bytes
app.add_middleware(GZipMiddleware, minimum_size=500)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Max 3 requests per hour. "
                      "Please try again later."
        }
    )

app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)


# ──────────────────────────────────────────────
# Global exception handler — never leak stack traces
# ──────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled error on {request.url.path}: {type(exc).__name__}"
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again."}
    )


# ──────────────────────────────────────────────
# CORS Middleware
# ──────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Secret-Key"],
)


# ──────────────────────────────────────────────
# Security Headers + Cache Control Middleware
# ──────────────────────────────────────────────
@app.middleware("http")
async def add_security_and_cache_headers(request: Request, call_next):
    # Block requests with empty or missing User-Agent
    user_agent = request.headers.get("user-agent", "").strip()
    if not user_agent and request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Forbidden"}
        )

    response = await call_next(request)

    # Security headers
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), "
        "payment=(), usb=(), magnetometer=(), gyroscope=()"
    )
    response.headers["Strict-Transport-Security"] = (
        "max-age=63072000; includeSubDomains; preload"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
        "https://fonts.gstatic.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

    # Remove server identification header
    if "server" in response.headers:
        del response.headers["server"]

    # X-Robots-Tag on API routes only
    path = request.url.path
    if path.startswith("/api/") or path == "/health":
        response.headers["X-Robots-Tag"] = "noindex"

    # Cache control for static assets vs pages vs API
    if path.startswith("/static/") or path.endswith((".css", ".js", ".woff2")):
        response.headers["Cache-Control"] = "public, max-age=86400, immutable"
    elif path in ("/", "/privacy", "/terms"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache"

    return response


# ──────────────────────────────────────────────
# Request body size limiter
# ──────────────────────────────────────────────
@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large. Max 50 KB."}
            )
    return await call_next(request)


# ──────────────────────────────────────────────
# Page Routes (HTML Serving)
# ──────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    """Serve the main HTML page."""
    return _serve_static_page("index.html")


@app.get("/privacy")
async def serve_privacy():
    """Serve the privacy policy page."""
    return _serve_static_page("privacy.html")


@app.get("/terms")
async def serve_terms():
    """Serve the terms of service page."""
    return _serve_static_page("terms.html")


@app.get("/sitemap.xml")
async def serve_sitemap():
    """Serve the sitemap for search engines."""
    filepath = os.path.join(STATIC_DIR, "sitemap.xml")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Sitemap not found")
    with open(filepath, 'r', encoding='utf-8') as f:
        from starlette.responses import Response
        return Response(content=f.read(), media_type="application/xml")


@app.get("/robots.txt")
async def serve_robots():
    """Serve robots.txt for search engine crawlers."""
    filepath = os.path.join(STATIC_DIR, "robots.txt")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="robots.txt not found")
    with open(filepath, 'r', encoding='utf-8') as f:
        from starlette.responses import Response
        return Response(content=f.read(), media_type="text/plain")


# ──────────────────────────────────────────────
# API Endpoints
# ──────────────────────────────────────────────

@app.post("/api/generate")
@limiter.limit("3/hour")
async def generate_report(request: Request):
    """
    Accept a list of YouTube URLs/handles, validate them,
    create a background job, and return the job_id.
    Protected by SECRET_KEY validation via X-Secret-Key header.
    """
    # ── SECRET_KEY validation ──
    # Requests from the app's own frontend (same origin) are trusted via
    # Origin / Referer check.  External API consumers must supply the key.
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    is_same_origin = (
        origin == ALLOWED_ORIGIN
        or referer.startswith(ALLOWED_ORIGIN)
    )
    if not is_same_origin:
        request_key = request.headers.get("X-Secret-Key", "")
        if not request_key or request_key != SECRET_KEY:
            raise HTTPException(
                status_code=403,
                detail="Forbidden: invalid or missing secret key",
            )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid request format")

    raw_input = body.get("channels", "")
    if not raw_input or not isinstance(raw_input, str):
        raise HTTPException(
            status_code=400,
            detail="Missing 'channels' field."
        )

    if len(raw_input) > 10_000:
        raise HTTPException(
            status_code=400,
            detail="Input text too long. Max 10,000 characters."
        )

    try:
        channels = extract_channels(raw_input)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if len(channels) > MAX_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_CHANNELS} channels allowed per request."
        )

    job_id = str(uuid.uuid4())

    set_job(job_id, {
        'status': 'queued',
        'progress': '0',
        'total': str(len(channels)),
        'download_url': '',
        'error': '',
    })

    _run_job_in_thread(job_id, channels)

    return JSONResponse({
        "job_id": job_id,
        "channels_count": len(channels),
        "message": "Job queued successfully"
    })


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """Return current job status and progress."""
    _validate_uuid(job_id)

    job_data = get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found or expired")

    return JSONResponse({
        "job_id": job_id,
        "status": job_data.get("status", "unknown"),
        "progress": int(job_data.get("progress", 0)),
        "total": int(job_data.get("total", 0)),
        "download_url": job_data.get("download_url", ""),
        "error": job_data.get("error", ""),
    })


@app.get("/api/download/{job_id}")
async def download_pdf(job_id: str, background_tasks: BackgroundTasks):
    """Serve the generated PDF as a download."""
    _validate_uuid(job_id)

    job_data = get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found or expired")

    if job_data.get("status") != "complete":
        raise HTTPException(status_code=400, detail="PDF is not ready yet")

    safe_filename = f"{job_id}.pdf"
    pdf_path = os.path.join(PDF_DIR, safe_filename)
    real_pdf_path = os.path.realpath(pdf_path)
    real_pdf_dir = os.path.realpath(PDF_DIR)

    if not real_pdf_path.startswith(real_pdf_dir):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not os.path.exists(pdf_path):
        raise HTTPException(
            status_code=404,
            detail="PDF file not found — it may have expired"
        )

    async def delete_pdf_later():
        await asyncio.sleep(PDF_EXPIRY_SECONDS)
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except Exception:
            pass

    background_tasks.add_task(delete_pdf_later)

    return FileResponse(
        path=pdf_path,
        filename=f"YT_Leads_Report_{job_id[:8]}.pdf",
        media_type="application/pdf",
    )


# ──────────────────────────────────────────────
# Health Check (minimal — no internal details)
# ──────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/health/debug")
async def health_debug(request: Request):
    """Secured debug endpoint — requires SECRET_KEY."""
    key = request.headers.get("X-Secret-Key", "")
    if key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

    import sys
    import subprocess as sp
    import glob

    browsers_path = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', 'NOT SET')
    browsers_dir = '/opt/render/project/src/.browsers'

    # Check if browser dir exists and list contents
    dir_exists = os.path.exists(browsers_dir)
    dir_contents = []
    chrome_binary = None
    if dir_exists:
        try:
            for root, dirs, files in os.walk(browsers_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    rel = os.path.relpath(fp, browsers_dir)
                    if 'chrome' in f.lower():
                        dir_contents.append(f"** {rel}")
                        if f == 'chrome' or f == 'chromium':
                            chrome_binary = fp
                    elif len(dir_contents) < 20:
                        dir_contents.append(rel)
        except Exception as e:
            dir_contents.append(f"ERROR: {e}")

    # Also check default cache path
    cache_path = os.path.expanduser('~/.cache/ms-playwright')
    cache_exists = os.path.exists(cache_path)
    cache_chromes = glob.glob(f'{cache_path}/chromium-*/chrome-linux/chrome')

    # Also check /opt/render/.cache
    render_cache = '/opt/render/.cache/ms-playwright'
    render_cache_exists = os.path.exists(render_cache)
    render_cache_chromes = glob.glob(f'{render_cache}/chromium-*/chrome-linux/chrome')

    # Try subprocess test
    sub_stdout = ""
    sub_stderr = ""
    sub_exit = -1
    try:
        test = sp.run(
            [sys.executable, '-c',
             'import os; os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/render/project/src/.browsers"; '
             'from playwright.sync_api import sync_playwright; '
             'p = sync_playwright().start(); '
             'b = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage","--single-process","--no-zygote"]); '
             'b.close(); p.stop(); print("OK")'],
            capture_output=True, text=True, timeout=30,
        )
        sub_stdout = test.stdout[:500]
        sub_stderr = test.stderr[:1500]
        sub_exit = test.returncode
    except Exception as e:
        sub_stderr = f"{type(e).__name__}: {e}"

    return JSONResponse({
        "env_browsers_path": browsers_path,
        "browsers_dir_exists": dir_exists,
        "browsers_dir_contents": dir_contents[:30],
        "chrome_binary_found": chrome_binary,
        "cache_exists": cache_exists,
        "cache_chromes": cache_chromes[:5],
        "render_cache_exists": render_cache_exists,
        "render_cache_chromes": render_cache_chromes[:5],
        "subprocess_exit": sub_exit,
        "subprocess_stdout": sub_stdout,
        "subprocess_stderr": sub_stderr,
    })
# ──────────────────────────────────────────────
# Static files & 404 fallback (must be last)
# ──────────────────────────────────────────────

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(404)
async def custom_404_handler(request: Request, exc: HTTPException):
    """Serve custom 404 page for HTML requests, JSON for API."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "Not found"}
        )
    four_oh_four = os.path.join(STATIC_DIR, "404.html")
    if os.path.exists(four_oh_four):
        with open(four_oh_four, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read(), status_code=404)
    return JSONResponse(status_code=404, content={"detail": "Not found"})
