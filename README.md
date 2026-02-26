# 🎯 YT Lead Gen — YouTube Lead Generator

Paste YouTube channel URLs → get a professional PDF report with full screenshots of their videos pages. Perfect for freelancers pitching video editing, thumbnail design, or channel management services.

## ⚡ Tech Stack

- **Backend:** FastAPI + Celery + Redis
- **Browser:** Playwright (headless Chromium)
- **PDF:** FPDF2 + Pillow
- **Frontend:** Single HTML file + Tailwind CSS (CDN)
- **Deployment:** Render.com (free tier)

---

## 🚀 Local Development Setup

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/yt-lead-gen.git
cd yt-lead-gen
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Redis URL and settings
```

### 3. Start Redis

Option A — **Local Redis:**

```bash
redis-server
```

Option B — **Upstash (free cloud Redis):**

1. Go to [upstash.com](https://upstash.com) and create a free Redis database
2. Copy the Redis URL (starts with `rediss://`)
3. Paste it into your `.env` file as `REDIS_URL`

### 4. Start the Worker

```bash
celery -A worker.celery_app worker --loglevel=info --concurrency=1
```

### 5. Start the Web Server

```bash
uvicorn main:app --reload --port 8000
```

### 6. Open the App

Visit [http://localhost:8000](http://localhost:8000) in your browser.

---

## 🌐 Deploy to Render.com (Free)

### Step 1 — Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/yt-lead-gen.git
git push -u origin main
```

### Step 2 — Create Upstash Redis

1. Go to [upstash.com](https://upstash.com) → Create a new Redis database
2. Copy the **Redis URL** (format: `rediss://default:PASSWORD@HOST:PORT`)

### Step 3 — Deploy on Render

1. Go to [render.com](https://render.com) → **New** → **Blueprint**
2. Connect your GitHub repo
3. Render will auto-detect `render.yaml` and create both services
4. Set the environment variables:
   - `REDIS_URL` = your Upstash Redis URL
   - `ALLOWED_ORIGIN` = `https://yt-lead-gen-web.onrender.com` (your Render domain)

### Step 4 — Verify

Visit your Render web service URL. Paste some YouTube channel URLs and generate a PDF!

---

## 🔒 Security Features

- ✅ Input validation — only valid YouTube URLs/handles accepted
- ✅ Rate limiting — 3 requests per IP per hour
- ✅ Max 30 channels per request
- ✅ 15-minute job timeout
- ✅ Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
- ✅ CORS restricted to your domain
- ✅ PDF auto-deleted after 10 minutes
- ✅ UUID filenames (non-guessable)
- ✅ No permanent data storage
- ✅ Playwright runs sandboxed with minimal permissions

---

## 📁 Project Structure

```
yt-lead-gen/
├── main.py                  # FastAPI app + API endpoints
├── worker.py                # Celery background worker
├── screenshot_capture.py    # Playwright browser automation
├── pdf_generator.py         # FPDF2 PDF generation
├── url_extractor.py         # URL/handle validation
├── static/
│   └── index.html           # Frontend (Tailwind CSS + vanilla JS)
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
├── .gitignore               # Git ignore rules
├── render.yaml              # Render.com deployment config
└── README.md                # This file
```

## 📝 License

MIT — Use it, modify it, ship it. Built for hustlers. 🚀
