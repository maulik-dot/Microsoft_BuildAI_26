"""
Universal Comparison Agent — hybrid approach:

1. Start with KNOWN reliable sites from agent memory (fast, no wasted steps)
2. Use Google to discover ONE additional source to cross-check
3. Skip any site marked blocked in memory
4. Return comparison table across sources that actually worked

Why hybrid: Pure Google-discovery fails for flights because all top results
(Google Flights, MakeMyTrip, Skyscanner) have heavy bot protection.
Starting with memory-confirmed working sites guarantees at least one result.
"""

from backend.tools.browser import run_deep_task
from backend.tools.planner import _call_llm
from backend.memory.agent_memory import get_general_context, update_general, _load as load_memory


# Sites confirmed to work reliably for each category
RELIABLE_SITES = {
    "flights":   ["ixigo.com/flights", "goibibo.com"],
    "hotels":    ["ixigo.com/hotels", "goibibo.com/hotels"],
    "products":  ["flipkart.com", "amazon.in"],
    "laptops":   ["flipkart.com", "amazon.in", "croma.com"],
    "phones":    ["flipkart.com", "amazon.in"],
    "courses":   ["udemy.com", "youtube.com"],
    "jobs":      ["naukri.com", "indeed.co.in"],
    "default":   ["flipkart.com", "amazon.in"],
}

# Sites with aggressive bot detection — skip immediately
BLOCKED_SITES = [
    "google.com/flights", "flights.google.com",
    "makemytrip.com", "skyscanner.com", "kayak.com",
    "booking.com", "expedia.com",
]


def _get_category(query: str) -> str:
    """Detect which product/service category this query belongs to."""
    q = query.lower()
    if any(w in q for w in ["flight", "fly", "airline", "airfare"]): return "flights"
    if any(w in q for w in ["hotel", "stay", "accommodation", "room"]): return "hotels"
    if any(w in q for w in ["laptop", "notebook", "macbook", "chromebook"]): return "laptops"
    if any(w in q for w in ["phone", "mobile", "iphone", "samsung", "smartphone"]): return "phones"
    if any(w in q for w in ["course", "tutorial", "learn", "training", "udemy"]): return "courses"
    if any(w in q for w in ["job", "career", "salary", "hiring"]): return "jobs"
    return "default"


def _get_blocked_from_memory() -> list[str]:
    """Get all sites marked as blocked across any task type."""
    memory = load_memory()
    blocked = list(BLOCKED_SITES)
    for task_data in memory.values():
        blocked.extend(task_data.get("blocked", []))
    return list(set(blocked))


async def run_comparison(query: str, task_id: str = "") -> dict:
    """
    Hybrid comparison: reliable known sites + Google-discovered alternative.
    """
    memory_ctx = get_general_context(query)
    category = _get_category(query)
    reliable = RELIABLE_SITES.get(category, RELIABLE_SITES["default"])
    blocked = _get_blocked_from_memory()

    # Filter out any blocked sites from reliable list
    usable = [s for s in reliable if not any(b in s for b in blocked)]
    if not usable:
        usable = reliable[:1]  # always have at least one to try

    sites_str = " and ".join(usable[:2])

    # Build a discover-and-compare prompt
    discover_hint = _call_llm(f"""For this price comparison query: "{query}"

I already know these sites work reliably: {', '.join(usable[:2])}
These sites have bot protection and should be AVOIDED: {', '.join(BLOCKED_SITES[:5])}

What ONE additional site (not in either list above) might have competitive prices?
Consider: regional Indian sites, direct sellers, official brand sites, comparison aggregators.
Return ONLY the website URL (e.g. "croma.com"). Nothing else.""", task_type="planning")

    discover_hint = discover_hint.strip().replace("https://", "").replace("http://", "").split("/")[0] if discover_hint else ""
    # Validate it's not a blocked site
    if any(b in discover_hint for b in blocked) or not discover_hint:
        discover_hint = ""

    all_sources = usable[:2]
    if discover_hint and discover_hint not in all_sources:
        all_sources.append(discover_hint)

    sources_list = "\n".join(f"- https://{s}" for s in all_sources)

    task = f"""{memory_ctx}

COMPARISON QUERY: {query}

SEARCH STRATEGY:
You MUST check prices on these specific sites (they are confirmed to work):
{sources_list}

IMPORTANT — AVOID these sites (bot detection, will waste your time):
{chr(10).join(f'- {s}' for s in BLOCKED_SITES[:6])}

STEP-BY-STEP INSTRUCTIONS:

For EACH site in the list above:
1. Navigate directly to the URL
2. Search for the exact item/option in the query
3. Extract: name, price, any discounts/offers, rating if shown, availability, direct URL
4. If a site blocks you or shows CAPTCHA — immediately move to the next site, do NOT retry

After checking all sites:
5. Build a comparison table:
   | Site | Price | Discount | Rating | Notes |
6. Clearly state: BEST VALUE = [site] at [price]
7. Include direct links to each listing found

Be efficient — spend max 8-10 steps per site, then move on."""

    result = await run_deep_task(task, task_type="research", task_id=task_id, max_steps=30)

    # If result is empty, try with just the most reliable single source
    if not result or len(result.strip()) < 100:
        fallback_task = f"""Find the price of this: {query}

Go directly to https://{usable[0]} and search.
Extract: exact product name, current price, any offers, direct link.
Return the price information you find."""
        result = await run_deep_task(fallback_task, task_type="research", task_id=task_id, max_steps=15)

    update_general(query, result, success=bool(result and len(result) > 100))
    return {"query": query, "result": result, "task_type": "comparison"}
