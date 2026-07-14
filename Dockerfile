# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

# ── System dependencies for Playwright/Chromium + supervisor (as root) ──
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    # Chromium runtime deps
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    libxshmfence1 libgl1 fonts-liberation libappindicator3-1 \
    xdg-utils libdbus-1-3 libglib2.0-0 \
    # Process supervisor
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces (and good container practice) run the app as UID 1000, not
# root. Create that user and keep Chromium in a shared, world-executable path so
# the non-root runtime can find and launch it.
RUN useradd -m -u 1000 user
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    # Chromium runs headless + sandbox-less in the container (see browser.py)
    HEADLESS=true \
    DISPLAY=""

# ── Python dependencies (root → installed system-wide, readable by the user) ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Playwright Chromium + its OS deps → shared browser path, world-executable ──
RUN python -m playwright install chromium --with-deps \
    && chmod -R a+rx /ms-playwright

# ── App code, owned by the runtime user so it can write the SQLite DB + caches ──
RUN mkdir -p /app && chown user:user /app
WORKDIR /app
COPY --chown=user . .
RUN mkdir -p uploads /tmp/vayu && chown -R user:user uploads /tmp/vayu

COPY supervisord.conf /etc/supervisor/conf.d/vayu.conf

# Railway/HF set PORT; app_port in README.md (8000) matches this EXPOSE.
USER user
EXPOSE 8000

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/vayu.conf"]
