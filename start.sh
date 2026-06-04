#!/bin/bash

# Copy env if not exists
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your ANTHROPIC_API_KEY"
  exit 1
fi

# Install playwright browsers if needed
python -m playwright install chromium

# Start backend in background
echo "Starting FastAPI backend..."
uvicorn backend.main:app --reload --port 8000 &
BACKEND_PID=$!

# Wait for backend to be ready
sleep 2

# Start Chainlit frontend
echo "Starting Chainlit frontend..."
chainlit run frontend/app.py --port 8001

# Cleanup on exit
kill $BACKEND_PID
