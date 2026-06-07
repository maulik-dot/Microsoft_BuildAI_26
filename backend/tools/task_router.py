"""
Task Router — self-learning, zero hardcoded site lists.

Routes queries to the most appropriate agent based on query intent.
The agents themselves discover and learn which sites work — no pre-programmed lists.

Routing logic:
- comparison  → Universal comparison agent (Google discovers sources, memory refines over time)
- travel      → Travel crew (structured flight+hotel itinerary)
- jobs        → Jobs crew
- hackathon   → Hackathon crew
- research    → General research agent
"""

import json
from backend.tools.planner import _call_llm


def classify(query: str) -> str:
    """Classify the query into the right agent type."""
    from datetime import datetime
    today = datetime.now().strftime("%B %d, %Y")

    prompt = f"""Classify this query into exactly one category. Return ONLY the category name.

Today's date: {today}
Query: "{query}"

Categories:
- comparison: user wants prices, deals, cheapest option across multiple stores. Key signals: "price", "cheapest", "compare prices", "under ₹X", "Flipkart vs Amazon"
- travel: user wants flight + hotel itinerary with specific cities and dates
- jobs: user wants job listings, salary info, career openings
- hackathon: user specifically mentions hackathon, coding contest, devfolio, unstop
- research: EVERYTHING ELSE — facts, stats, how-to, coding problems, YouTube, news, "how many", "what is", "find me", "solved", "acceptance rate", programming, general web research

IMPORTANT rules to avoid misclassification:
- "how many people solved it", "acceptance rate", "solved by" = research (NOT hackathon)
- "find on YouTube", "most viewed video" = research
- "DSA playlist", "study plan" = research
- "if the video has X views" = research (conditional instruction)
- Only use hackathon when user explicitly asks for hackathon events/competitions

Return only: comparison | travel | jobs | hackathon | research"""

    result = _call_llm(prompt, task_type="planning")
    result = result.strip().lower().split()[0] if result else "research"
    valid = {"comparison", "travel", "jobs", "hackathon", "research"}
    return result if result in valid else "research"


async def route(query: str, task_id: str = "") -> dict:
    task_type = classify(query)

    if task_type == "comparison":
        from backend.agents.comparison.crew import run_comparison
        return await run_comparison(query, task_id=task_id)

    elif task_type == "travel":
        return await _run_travel(query, task_id)

    elif task_type == "jobs":
        return await _run_jobs(query, task_id)

    elif task_type == "hackathon":
        return await _run_hackathon(query, task_id)

    else:
        from backend.agents.research.agent import run_research
        return await run_research(query, task_id=task_id)


# ── Specialized crew runners ──────────────────────────────────────────────

async def _run_travel(query: str, task_id: str) -> dict:
    params = _parse_travel(query)
    from backend.agents.travel.crew import run_travel_booking
    from backend.models.schemas import TravelRequest
    result = await run_travel_booking(TravelRequest(**params), task_id=task_id)
    return {"query": query, "result": result.get("summary", ""), "task_type": "travel"}


async def _run_jobs(query: str, task_id: str) -> dict:
    raw = _call_llm(f"""Extract job search params from: "{query}"
JSON only: {{"job_titles": ["..."], "location": "...", "platforms": ["naukri"]}}""",
        task_type="planning")
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


# ── Param parsers ──────────────────────────────────────────────────────────

def _parse_travel(query: str) -> dict:
    from datetime import datetime
    year = datetime.now().year
    raw = _call_llm(f"""Extract travel params from: "{query}"
JSON: {{"from_city": "...", "to_city": "...", "departure_date": "YYYY-MM-DD", "return_date": null, "budget": null}}
Assume year {year} if not specified. JSON only.""", task_type="planning")
    try:
        params = _parse_json(raw)
        params.setdefault("from_city", "Mumbai")
        params.setdefault("to_city", "Delhi")
        params.setdefault("departure_date", f"{year}-06-15")
        return params
    except Exception:
        return {"from_city": "Mumbai", "to_city": "Delhi", "departure_date": f"{year}-06-15"}


def _parse_json(raw: str) -> dict:
    if not raw: return {}
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw.strip())
