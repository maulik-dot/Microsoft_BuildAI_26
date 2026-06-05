"""
Task Router — classifies a query and dispatches to the right agent.

Routing hierarchy:
1. comparison  → Universal comparison agent (Google-first site discovery, any domain)
2. travel      → Travel crew (Ixigo as starting point, but comparison agent used for best-of-web)
3. jobs        → Jobs crew (Naukri)
4. hackathon   → Hackathon crew (Devfolio/Unstop)
5. research    → General research agent

Key principle: For ANY price/deal/comparison query, always use the comparison agent
which starts with Google to discover the best sources dynamically.
"""

import json
from backend.tools.planner import _call_llm


TASK_TYPES = {
    "comparison":    "Price comparison, best deal, cheapest option — for ANY item (flights, products, hotels, services)",
    "travel":        "Trip planning with specific itinerary (need flights AND hotels together as a package)",
    "jobs":          "Job search — find openings, apply, career opportunities",
    "hackathon":     "Hackathon or coding competition discovery",
    "research":      "General web research, how-to, facts, news, anything not covered above",
}


def classify(query: str) -> str:
    """Classify query into the right agent type."""
    prompt = f"""Classify this query into exactly one category. Return ONLY the category name.

Query: "{query}"

Categories:
- comparison: user wants to COMPARE prices, find cheapest/best option, or check a specific price across multiple sites. Examples: "cheapest flight", "best price for X", "compare X vs Y", "find X under ₹N", "where to buy X cheapest"
- travel: user wants a full trip plan with BOTH flights and hotels together (itinerary planning)
- jobs: user wants to find job openings, apply for jobs, check salaries
- hackathon: user wants to find hackathons, coding competitions, events
- research: general information, how-to questions, news, explanations, anything else

IMPORTANT:
- If the query mentions price, cost, compare prices, cheapest, best deal, "under ₹X", or "how much does X cost" — classify as comparison.
- "Best restaurants" / "best places" / "best tools" = research (no price intent)
- "Cheapest restaurant" / "restaurant under ₹500" = comparison (has price intent)

Return only: comparison | travel | jobs | hackathon | research"""

    result = _call_llm(prompt, task_type="planning")
    result = result.strip().lower().split()[0] if result else "research"
    return result if result in TASK_TYPES else "research"


async def route(query: str, task_id: str = "") -> dict:
    """Route the query to the best agent."""
    task_type = classify(query)

    if task_type == "comparison":
        return await _run_comparison(query, task_id)
    elif task_type == "travel":
        return await _run_travel(query, task_id)
    elif task_type == "jobs":
        return await _run_jobs(query, task_id)
    elif task_type == "hackathon":
        return await _run_hackathon(query, task_id)
    else:
        return await _run_research(query, task_id)


# ── Specialized runners ────────────────────────────────────────────────────

async def _run_comparison(query: str, task_id: str) -> dict:
    """
    Universal comparison — Google discovers best sources, agent compares them.
    Works for flights, products, hotels, services — anything price-related.
    """
    from backend.agents.comparison.crew import run_comparison
    return await run_comparison(query, task_id=task_id)


async def _run_travel(query: str, task_id: str) -> dict:
    """Full trip itinerary — uses travel crew for structured flight+hotel booking."""
    params = _parse_travel(query)
    from backend.agents.travel.crew import run_travel_booking
    from backend.models.schemas import TravelRequest
    result = await run_travel_booking(TravelRequest(**params), task_id=task_id)
    return {"query": query, "result": result.get("summary", ""), "task_type": "travel"}


async def _run_jobs(query: str, task_id: str) -> dict:
    raw = _call_llm(f"""Extract job search params from: "{query}"
Return JSON: {{"job_titles": ["..."], "location": "...", "platforms": ["naukri"]}}
Only valid JSON.""", task_type="planning")
    try:
        params = _parse_json(raw)
        params.setdefault("job_titles", [query[:50]])
        params.setdefault("location", "India")
        params.setdefault("platforms", ["naukri"])
    except Exception:
        params = {"job_titles": [query[:50]], "location": "India", "platforms": ["naukri"]}

    from backend.agents.jobs.crew import run_job_applications
    from backend.models.schemas import JobRequest
    result = await run_job_applications(JobRequest(**params))
    return {"query": query, "result": result.get("summary", ""), "task_type": "jobs"}


async def _run_hackathon(query: str, task_id: str) -> dict:
    from backend.agents.hackathon.crew import find_hackathons
    from backend.models.schemas import HackathonRequest
    result = await find_hackathons(HackathonRequest(
        resume_text=query, platforms=["devfolio", "unstop"],
    ))
    return {"query": query, "result": result.get("result", ""), "task_type": "hackathon"}


async def _run_research(query: str, task_id: str) -> dict:
    from backend.agents.research.agent import run_research
    return await run_research(query, task_id=task_id)


# ── Helpers ───────────────────────────────────────────────────────────────

def _parse_travel(query: str) -> dict:
    raw = _call_llm(f"""Extract travel params from: "{query}"
Return JSON: {{"from_city": "...", "to_city": "...", "departure_date": "YYYY-MM-DD", "return_date": null, "budget": null}}
Assume year 2026 if not specified. Only valid JSON.""", task_type="planning")
    try:
        params = _parse_json(raw)
        params.setdefault("from_city", "Mumbai")
        params.setdefault("to_city", "Delhi")
        params.setdefault("departure_date", "2026-06-15")
        return params
    except Exception:
        return {"from_city": "Mumbai", "to_city": "Delhi", "departure_date": "2026-06-15"}


def _parse_json(raw: str) -> dict:
    if not raw: return {}
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw.strip())
