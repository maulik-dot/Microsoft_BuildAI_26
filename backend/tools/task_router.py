"""
Task Router — self-learning, zero hardcoded site lists.

Routes queries to the most appropriate agent based on query intent.
The agents themselves discover and learn which sites work — no pre-programmed lists.

Routing logic:
- comparison  → Universal comparison agent (Google discovers sources, memory refines over time)
- travel      → Travel crew (structured flight+hotel itinerary)
- research    → General research agent
"""

import json
from backend.tools.planner import _call_llm


def classify(query: str) -> str:
    """Classify the query into either comparison or research."""
    from datetime import datetime
    today = datetime.now().strftime("%B %d, %Y")

    prompt = f"""Classify this query into exactly one category. Return ONLY the category name.

Today's date: {today}
Query: "{query}"

Categories:
- comparison: user wants a direct price comparison, deals, cheapest option across multiple stores, or comparing specific options/products. Key signals: "compare", "cheapest", "vs", "under ₹X", "best deal".
- research: EVERYTHING ELSE — general questions, finding information, lists of jobs, flights, hotel details, hackathons, facts, specs, tutorials, YouTube search, programming queries.

Return only: comparison | research"""

    result = _call_llm(prompt, task_type="planning")
    result = result.strip().lower().split()[0] if result else "research"
    valid = {"comparison", "research"}
    return result if result in valid else "research"


async def route(query: str, task_id: str = "") -> dict:
    task_type = classify(query)

    if task_type == "comparison":
        from backend.agents.comparison.crew import run_comparison
        return await run_comparison(query, task_id=task_id)
    else:
        from backend.agents.research.agent import run_research
        return await run_research(query, task_id=task_id)


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
