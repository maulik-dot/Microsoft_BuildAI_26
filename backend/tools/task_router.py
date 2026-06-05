"""
Task Router — classifies a query and dispatches it to the right agent.

Specialized agents are fast and focused (10-15 steps, known sites).
The general research agent handles everything else (open-ended queries).

Why this matters:
- Travel queries sent to general agent → lands on Google Flights (30+ steps, often fails)
- Travel queries sent to travel crew → goes directly to Ixigo (8-12 steps, reliable)
"""

import json
from backend.tools.planner import _call_llm


TASK_TYPES = {
    "travel":        "Flight or hotel search with specific cities and dates",
    "jobs":          "Job search on platforms like Naukri or LinkedIn",
    "price_monitor": "Price check or price comparison for a specific product",
    "hackathon":     "Hackathon or coding competition discovery",
    "research":      "General web research, comparisons, facts, anything else",
}


def classify(query: str) -> str:
    """Return task type: travel | jobs | price_monitor | hackathon | research"""
    prompt = f"""Classify this query into exactly one category. Return ONLY the category name.

Query: "{query}"

Categories:
- travel: mentions flights, hotels, trip planning with cities/dates
- jobs: mentions jobs, hiring, salary, naukri, linkedin, careers
- price_monitor: mentions price of a specific product, compare prices, under ₹X
- hackathon: mentions hackathons, coding competitions, devfolio, unstop
- research: anything else — general information, how-to, comparisons, news, etc.

Return only: travel | jobs | price_monitor | hackathon | research"""

    result = _call_llm(prompt, task_type="planning")
    result = result.strip().lower().split()[0] if result else "research"
    return result if result in TASK_TYPES else "research"


async def route(query: str, task_id: str = "") -> dict:
    """
    Route the query to the best agent and return the result dict.
    Specialized agents are faster and more reliable for known domains.
    """
    task_type = classify(query)

    if task_type == "travel":
        return await _run_travel(query, task_id)
    elif task_type == "jobs":
        return await _run_jobs(query, task_id)
    elif task_type == "price_monitor":
        return await _run_price(query, task_id)
    elif task_type == "hackathon":
        return await _run_hackathon(query, task_id)
    else:
        return await _run_research(query, task_id)


# ── Specialized runners ────────────────────────────────────────────────────

async def _run_travel(query: str, task_id: str) -> dict:
    """Extract travel params from natural language and run the travel crew."""
    params = _parse_travel(query)
    from backend.agents.travel.crew import run_travel_booking
    from backend.models.schemas import TravelRequest
    result = await run_travel_booking(TravelRequest(**params), task_id=task_id)
    return {"query": query, "result": result.get("summary", ""), "task_type": "travel"}


async def _run_jobs(query: str, task_id: str) -> dict:
    from backend.tools.planner import _call_llm
    # Extract job search params
    raw = _call_llm(f"""Extract job search parameters from: "{query}"
Return JSON: {{"job_titles": ["..."], "location": "...", "platforms": ["naukri"]}}
Only valid JSON, no markdown.""", task_type="planning")
    try:
        params = _parse_json(raw)
        params.setdefault("job_titles", ["Software Engineer"])
        params.setdefault("location", "India")
        params.setdefault("platforms", ["naukri"])
    except Exception:
        params = {"job_titles": [query[:50]], "location": "India", "platforms": ["naukri"]}

    from backend.agents.jobs.crew import run_job_applications
    from backend.models.schemas import JobRequest
    result = await run_job_applications(JobRequest(**params))
    return {"query": query, "result": result.get("summary", ""), "task_type": "jobs"}


async def _run_price(query: str, task_id: str) -> dict:
    raw = _call_llm(f"""Extract price check parameters from: "{query}"
Return JSON: {{"product_name": "...", "target_price": 0, "platforms": ["flipkart","amazon"]}}
Only valid JSON, no markdown.""", task_type="planning")
    try:
        params = _parse_json(raw)
        params.setdefault("product_name", query[:60])
        params.setdefault("target_price", 99999)
        params.setdefault("platforms", ["flipkart", "amazon"])
    except Exception:
        params = {"product_name": query[:60], "target_price": 99999, "platforms": ["flipkart", "amazon"]}

    from backend.agents.price_monitor.crew import check_price
    from backend.models.schemas import PriceMonitorRequest
    result = await check_price(PriceMonitorRequest(**params))
    return {"query": query, "result": result.get("summary", ""), "task_type": "price_monitor"}


async def _run_hackathon(query: str, task_id: str) -> dict:
    from backend.agents.hackathon.crew import find_hackathons
    from backend.models.schemas import HackathonRequest
    result = await find_hackathons(HackathonRequest(
        resume_text=query,
        platforms=["devfolio", "unstop"],
    ))
    return {"query": query, "result": result.get("result", ""), "task_type": "hackathon"}


async def _run_research(query: str, task_id: str) -> dict:
    from backend.agents.research.agent import run_research
    return await run_research(query, task_id=task_id)


# ── Param parsers ──────────────────────────────────────────────────────────

def _parse_travel(query: str) -> dict:
    raw = _call_llm(f"""Extract travel parameters from: "{query}"
Return JSON with these fields:
- from_city: string (city name)
- to_city: string
- departure_date: string (YYYY-MM-DD, assume 2026 if year not specified)
- return_date: string or null
- budget: number in INR or null

Only valid JSON, no markdown.""", task_type="planning")

    try:
        params = _parse_json(raw)
        params.setdefault("from_city", "Mumbai")
        params.setdefault("to_city", "Delhi")
        params.setdefault("departure_date", "2026-06-15")
        return params
    except Exception:
        return {
            "from_city": "Mumbai", "to_city": "Delhi",
            "departure_date": "2026-06-15", "return_date": None, "budget": None,
        }


def _parse_json(raw: str) -> dict:
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())
