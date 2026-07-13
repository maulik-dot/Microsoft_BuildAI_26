#!/bin/bash

# Copy env if not exists
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your ANTHROPIC_API_KEY"
  exit 1
fi

# Install playwright browsers if needed
python -m playwright install chromium

# Start backend in foreground
echo "Starting FastAPI backend..."
uvicorn backend.main:app --reload --port 8000
