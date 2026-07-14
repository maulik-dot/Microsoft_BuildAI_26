---
title: Vayu
emoji: 🌀
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
pinned: false
short_description: Autonomous web-browsing AI agent that researches the live web
---

<p align="center">
  <img src="frontend/logo.png" alt="Vayu Logo" width="180"/>
</p>

# Vayu — Autonomous Web Learning Agent

> *"Vayu moves through the internet like wind — finding anything, anywhere, for you."*

Vayu is a **universal browser agent** that browses the live web on your behalf. Ask it anything — it opens a real browser, navigates websites, extracts data, verifies results, and learns reusable web flows from every run.

---

## Problem Statement

Finding information online today requires you to manually visit multiple sites, deal with cluttered UIs, compare fragmented data, and repeat this process every time. Agentic AI changes this: a single natural-language query should be enough to trigger a fully autonomous browser loop across the live web.

Existing solutions either hallucinate (LLMs without browser access) or are hardcoded to specific websites (rule-based scrapers). Vayu is neither — it discovers sources dynamically, verifies its own results, and learns from every run.

---

## Solution Overview

Vayu is a **FastAPI + browser-use + Gemini** system. An LLM-based intent router dynamically classifies tasks into either chit-chat or browser-agent mode:

| Query Type | Example | Agent |
|---|---|---|
| Browser Work | "Top AI startups in India 2025" | Browser Agent (10-capability pipeline) |
| Price/Option Comparison | "Samsung S24 vs iPhone 15 prices?" | Browser Agent (same pipeline, comparison-style output) |
| Travel, Jobs, & Hackathons | "Flights Mumbai → Delhi on June 15", "Python jobs in Bangalore" | Handled through the same universal browser loop |
| Conversational / Chit-chat | "hello", "thanks", "what is my name" | Handled directly via task router using context history (no browser task) |

---

## Architecture Overview

```
User Query (Vayu web UI — static SPA served by FastAPI)
        │
        ▼
  FastAPI Backend (/api/tasks)
        │
        ▼
  Task Router (LLM classify → chit_chat | browser_agent)
        │
   ┌────┴──────────────────────────────────────┐
   │                                           │
   ▼                                           ▼
Research Agent (10-capability pipeline)    Comparison Agent
   │                                       (Multi-source Google Discovery)
   ├─ 1. Goal Interpreter (ambiguity check)
   ├─ 2. Memory Retrieval (3-tier memory)
   ├─ 3. Query Engineer (Google operators)
   ├─ 4. Planner (step-by-step plan)
   ├─ 5. Browser Execution (browser-use + Gemini)
   │       ├─ Chain-of-thought per action
   │       ├─ Vision + DOM perception
   │       ├─ LLM self-judge on completion
   │       └─ Loop detection (window=8)
   ├─ 6. Verifier (confidence 0-100, gap list)
   └─ 7. Retry Loop (max 2) + Memory Update + Learner

  3-Tier Memory System
    ├─ agent_memory.json  — reusable site memory: works/blocked/tips/page flows
    ├─ general_memory.json — cross-query: top sources, patterns
    └─ web_knowledge.json — site flows, page types, obstacles, query patterns

  Two-Tier Model Router
   ├─ SMALL (gemini-flash-lite): planning, verification, classification
   └─ LARGE (gemini-2.5-flash → fallback chain): browser agent, reasoning

  Background Monitoring (APScheduler)
   └─ Price Monitor — every 30 min
```

---

## AI Tools Used

| Tool / Model | Role |
|---|---|
| **Google Gemini 2.5 Flash** | Primary browser agent (reasoning + vision) |
| **Gemini Flash Lite** | Planning, verification, classification (cost-optimized) |
| **browser-use** | Browser automation framework (Playwright + LLM control loop) |
| **Gemini API** | Live model availability probing + eval tracking |

### Key AI Design Patterns

- **Intent Classification** — LLM-based routing with few-shot rules, zero regex. Now supports context-aware chit-chat and conversational routing.
- **Conversational Memory** — Follow-up queries (like "What is my name?") utilize preceding conversation history directly inside chit-chat or browser contexts.
- **Query Engineering** — Google operator injection (`site:`, `filetype:`, date filters)
- **Temporal Awareness** — "latest/new" queries auto-inject current year into searches
- **Self-Verification** — Verifier LLM scores every result; triggers retry with hint
- **Self-Learning Loop** — `learner.py` extracts navigation patterns, site performance, obstacle solutions from every run and persists to `web_knowledge.json`
- **Two-Tier Model Routing** — live probes pick the best available Gemini model; eval tracker logs pass_rate/latency per model:task combo
- **Compounding Memory** — every run makes subsequent runs faster and more accurate

---

## Setup Instructions

### Prerequisites

- Python 3.11+
- Google API Key (Gemini) — [Get one free](https://aistudio.google.com/app/apikey)

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/vayu-agent
cd vayu-agent

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browser
python -m playwright install chromium

# 5. Configure environment
cp .env.example .env
# Edit .env and set:
#   GOOGLE_API_KEY=your_gemini_api_key
#   ANTHROPIC_API_KEY=your_key (optional, fallback)
```

### Running Locally

```bash
# Option A: Single script
bash start.sh

# Option B: Manual
uvicorn backend.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser — the FastAPI backend serves the Vayu web UI (`frontend/index.html`) directly.
Open **http://localhost:8000/knowledge** to inspect learned web flows and page patterns.

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_API_KEY` | ✅ Yes | Gemini API key (free tier works) |
| `ANTHROPIC_API_KEY` | Optional | Claude fallback |
| `GROQ_API_KEY` | Optional | Groq fallback |
| `BROWSER_USE_API_KEY` | Optional | browser-use Cloud (CAPTCHA bypass) |
| `APP_ENV` | Optional | `development` / `production` |

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | ≥0.115.0 | REST API backend |
| `uvicorn` | ≥0.30.0 | ASGI server |
| `browser-use` | 0.12.9 | Browser automation + LLM agent loop |
| `playwright` | 1.47.0 | Chromium browser control |
| `google-genai` | latest | Gemini API client |
| `apscheduler` | ≥3.10.0 | Background task scheduling |
| `sqlalchemy` | ≥2.0.0 | Task state persistence |
| `pdfplumber` | ≥0.11.0 | Resume PDF parsing |
| `httpx` | ≥0.27.0 | Async HTTP client |

---

## Project Structure

```
vayu/
├── backend/
│   ├── main.py                # FastAPI app, lifespan, browser pre-warm
│   ├── config.py              # Settings (pydantic-settings)
│   ├── agents/
│   │   ├── research/agent.py  # 10-capability browser-agent pipeline
│   │   └── price_monitor/     # Scheduled price alerts
│   ├── tools/
│   │   ├── browser.py         # browser-use wrapper, step streaming
│   │   ├── task_router.py     # LLM-based intent classifier + dispatcher
│   │   ├── planner.py         # plan_research / plan_task / replan
│   │   ├── goal_interpreter.py # Ambiguity detection, success condition
│   │   ├── verifier.py        # Result quality scoring + retry hints
│   │   ├── model_selector.py  # Two-tier model router + eval tracker
│   │   ├── learner.py         # Post-run self-learning loop
│   │   ├── query_engineer.py  # Google operator injection
│   │   ├── context.py         # System prompt builder
│   │   └── step_tracker.py    # Step pass/fail tracking for replanner
│   ├── memory/
│   │   └── agent_memory.py    # Generic persistent web memory
│   ├── monitoring/
│   │   └── scheduler.py       # APScheduler for price monitors
│   ├── api/
│   │   └── tasks.py           # REST endpoints (create/poll/stream tasks)
│   └── models/
│       └── schemas.py         # Pydantic request/response models
├── frontend/
│   ├── index.html             # Vayu web UI (static SPA, served by FastAPI)
│   └── vayu.mp4               # Animated brand mark
├── requirements.txt
├── start.sh
└── .env.example
```

---

## Team

| | |
|---|---|
| **Name** | Maulik Mahey |
| **Role** | Solo — Full-Stack AI Engineering |
| **Built** | Agent orchestration, browser automation, memory system, model routing, UI |

---

## Demo

🔗 **Live Demo:** [Add your deployment URL here]

**Example queries to try:**
```
Find flights from Mumbai to Delhi on July 10 under ₹5000
Compare price of iPhone 15 on Amazon vs Flipkart
Find Python ML engineer jobs in Bangalore with 1-3 years experience
Find open hackathons on Devfolio for ML/AI engineers
What is the acceptance rate of LeetCode 2149 problem?
```
