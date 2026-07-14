# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

# Install system dependencies for Playwright/Chromium
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

WORKDIR /app

# Copy and install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright + Chromium
RUN python -m playwright install chromium --with-deps

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p uploads /tmp/vayu

# Copy supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/vayu.conf

# Railway sets PORT env var — default to 8000 for FastAPI
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Run browser in headless mode on cloud — browser-use reads HEADLESS (the product
# image fetcher launches headless too). Without this the agent Chromium tries to
# open a window and fails in a display-less container.
ENV HEADLESS=true
ENV DISPLAY=""

EXPOSE 8000

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/vayu.conf"]
