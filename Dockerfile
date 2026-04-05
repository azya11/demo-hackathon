FROM python:3.12-slim

# System deps for Playwright (Chromium)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    libcairo2 libatspi2.0-0 libx11-6 libxcb1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium browser
RUN playwright install chromium

COPY app/ app/
COPY configs/ configs/
COPY prompts/ prompts/

# Persist the SQLite session database across runs
VOLUME ["/app/data"]

# The app needs GEMINI_API_KEY (or GOOGLE_API_KEY) for AI features.
# Set browser.mode to "launch" and browser.headless to true in
# configs/settings.json (or mount your own) for headless container use.
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main"]
