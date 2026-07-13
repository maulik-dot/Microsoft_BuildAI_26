"""
Query Engineer — transforms raw user queries into precision Google searches.

Applies 6 techniques automatically:
1. Operator injection    (site:, after:, intitle:, filetype:)
2. Query decomposition   (break complex → focused sub-queries)
3. Multi-angle search    (3 framings: price / deal / review)
4. Hypothetical seeding  (what would the perfect result look like?)
5. Recency anchoring     (add year when temporal intent detected)
6. Source targeting      (best sites per query type)
"""

import asyncio
import re
from datetime import datetime
from backend.tools.planner import _call_llm


# ── Source authority map ──────────────────────────────────────────────────────

SOURCE_MAP = {
    "price":      ["flipkart.com", "amazon.in", "croma.com"],
    "flights":    ["ixigo.com", "cleartrip.com", "goibibo.com"],
    "hotels":     ["ixigo.com", "makemytrip.com"],
    "jobs":       ["naukri.com", "indeed.co.in", "linkedin.com/jobs"],
    "courses":    ["udemy.com", "coursera.org", "youtube.com"],
    "hackathons": ["devfolio.co", "unstop.com", "hackerearth.com"],
    "news":       ["techcrunch.com", "thehindu.com", "ndtv.com"],
    "research":   ["arxiv.org", "scholar.google.com", "medium.com"],
    "reviews":    ["gsmarena.com", "digit.in", "91mobiles.com"],
}

# ── Intent detection ──────────────────────────────────────────────────────────

def _detect_intent(query: str) -> list[str]:
    """Detect query type. Specific intents checked before generic ones."""
    q = query.lower()
    intents = []
    # Specific first — these take priority over generic "price"
    if any(w in q for w in ["flight", "fly", "airline", "airfare"]): intents.append("flights")
    if any(w in q for w in ["hotel", "stay", "accommodation", "resort"]): intents.append("hotels")
    if any(w in q for w in ["job", "career", "hiring", "vacancy", "opening"]): intents.append("jobs")
    if any(w in q for w in ["course", "tutorial", "learn", "training", "certification"]): intents.append("courses")
    if any(w in q for w in ["hackathon", "competition", "contest", "challenge"]): intents.append("hackathons")
    if any(w in q for w in ["review", "rating", "worth", "specs", "comparison"]): intents.append("reviews")
    if any(w in q for w in ["news", "latest news", "breaking"]): intents.append("news")
    # Generic price — only if no specific intent already captured it
    if not intents and any(w in q for w in ["price", "cost", "cheap", "₹", "inr", "buy", "compare", "best deal"]):
        intents.append("price")
    elif any(w in q for w in ["price", "cost", "cheap", "₹", "compare"]) and "flights" not in intents:
        intents.append("price")
    return intents or ["research"]


def _detect_temporal(query: str) -> bool:
    """True if query needs recent results."""
    return bool(re.search(
        r'\b(latest|new|recent|upcoming|current|today|this year|2025|2026|now)\b',
        query, re.I
    ))


def _extract_price_range(query: str) -> tuple[str, str]:
    """Extract price constraints if present."""
    under = re.search(r'under\s*[₹rs\.]*\s*(\d[\d,]*)', query, re.I)
    above = re.search(r'above\s*[₹rs\.]*\s*(\d[\d,]*)', query, re.I)
    return (
        under.group(1).replace(',', '') if under else "",
        above.group(1).replace(',', '') if above else "",
    )


# ── Operator builder ──────────────────────────────────────────────────────────

def build_operator_queries(query: str) -> list[str]:
    """
    Generate 3-4 precision search queries with Google operators applied.
    Returns a list from most-specific to broad fallback.
    """
    year = datetime.now().year
    intents = _detect_intent(query)
    temporal = _detect_temporal(query)
    price_under, price_above = _extract_price_range(query)

    queries = []

    # ── Query 1: Site-targeted + temporal ──
    sources = []
    for intent in intents[:2]:
        sources.extend(SOURCE_MAP.get(intent, [])[:2])
    sources = sources[:3]

    q1 = f'"{query}"'
    if temporal:
        q1 += f" after:{year - 1}-01-01"
    if sources:
        site_expr = " OR ".join(f"site:{s}" for s in sources[:2])
        q1 += f" ({site_expr})"
    queries.append(q1)

    # ── Query 2: Price range operator if applicable ──
    if price_under:
        # Convert ₹40,000 → search with range
        q2 = re.sub(r'under\s*[₹rs\.]*\s*[\d,]+', '', query, flags=re.I).strip()
        q2 += f" ₹1..₹{price_under}"
        if temporal:
            q2 += f" {year}"
        queries.append(q2.strip())

    # ── Query 3: intitle for specific resource types ──
    if "courses" in intents or "tutorial" in query.lower():
        core = re.sub(r'(free|paid|best|top|under .+)', '', query, flags=re.I).strip()
        q3 = f'intitle:"{core}" tutorial {year}'
        queries.append(q3)
    elif "jobs" in intents:
        q3 = f'intitle:"jobs" {query} -{year - 3}'
        queries.append(q3)
    elif "reviews" in intents:
        q3 = f'intitle:"review" {query} {year}'
        queries.append(q3)
    else:
        # Generic multi-angle variation
        q3 = f'{query} {year} -site:quora.com -site:reddit.com'
        queries.append(q3)

    # ── Query 4: Broad fallback ──
    q4 = query
    if temporal and str(year) not in query:
        q4 += f" {year}"
    queries.append(q4)

    return queries


# ── Multi-angle generator ─────────────────────────────────────────────────────

def generate_angles(query: str) -> dict[str, str]:
    """
    Generate 3 angles for the same query:
    - direct: the core search
    - deal/comparison: find the best value
    - authority: find expert opinion
    """
    year = datetime.now().year
    intents = _detect_intent(query)

    angles = {}

    # Direct
    angles["direct"] = query if str(year) in query else f"{query} {year}"

    # Extract core subject (remove filler words for cleaner angle queries)
    core = re.sub(
        r'\b(find|search|get|show|tell me|what is|how to|latest|best|cheapest|under|above|in|on|for)\b',
        '', query, flags=re.I
    ).strip()
    core = re.sub(r'\s+', ' ', core).strip() or query

    # Deal/comparison angle
    if "flights" in intents:
        angles["deal"] = f"{core} cheapest fare discount {year}"
    elif "hotels" in intents:
        angles["deal"] = f"{core} best deal lowest price {year}"
    elif any(i in intents for i in ["price", "reviews"]):
        angles["deal"] = f"{core} best price offer discount coupon {year}"
    elif "courses" in intents:
        angles["deal"] = f"{core} free OR cheap coupon {year}"
    else:
        angles["deal"] = f"best {core} {year}"

    # Authority angle
    if "courses" in intents:
        angles["authority"] = f"{core} review worth it (site:reddit.com OR site:quora.com)"
    elif "jobs" in intents:
        angles["authority"] = f"{core} salary package experience (site:glassdoor.com OR site:ambitionbox.com)"
    elif "flights" in intents:
        angles["authority"] = f"{core} tips tricks cheapest booking {year}"
    elif any(i in intents for i in ["price", "reviews"]):
        angles["authority"] = f"{core} expert review vs alternatives {year}"
    else:
        angles["authority"] = f"{core} complete guide {year} (site:medium.com OR site:dev.to)"

    return angles


# ── Hypothetical seeder ───────────────────────────────────────────────────────

def generate_hypothetical(query: str) -> str:
    """
    Generate a hypothetical perfect answer, then extract search terms from it.
    This 'HyDE' technique finds pages that look like the answer.
    """
    result = _call_llm(f"""Generate a ONE-sentence hypothetical perfect answer to this query.
Include specific details: numbers, names, dates, prices.

Query: "{query}"

Example: Query "best python course 2026" → "The Complete Python Bootcamp on Udemy by Jose Portilla,
rated 4.7/5 with 500k students, available for ₹459 in 2026"

Hypothetical answer (one sentence, be specific):""", task_type="planning")

    if not result:
        return ""

    # Extract the most searchable noun phrases from the hypothesis
    # Focus on proper nouns, numbers, and quoted phrases
    result = result.strip().strip('"')

    # Build a targeted search from the hypothesis
    search = _call_llm(f"""Convert this hypothetical answer into a Google search query (max 10 words, no filler words):

Answer: "{result}"

Return only the search query:""", task_type="planning")

    return search.strip().strip('"') if search else ""


async def generate_hypothetical_async(query: str) -> str:
    """Async wrapper so the 2-call HyDE chain can overlap other planning LLM calls."""
    return await asyncio.to_thread(generate_hypothetical, query)


# ── Full enhanced plan ────────────────────────────────────────────────────────

def engineer_search_plan(query: str, hypothetical: str | None = None) -> str:
    """
    Build a complete engineered search plan for the agent.
    Returns a block of text to prepend to the task prompt.

    hypothetical: pass a precomputed HyDE string (or "" to skip it) to keep this
    function LLM-free so callers can parallelize the HyDE call. Default None keeps
    the original behaviour and computes it inline.
    """
    year = datetime.now().year
    temporal = _detect_temporal(query)
    intents = _detect_intent(query)
    operator_queries = build_operator_queries(query)
    angles = generate_angles(query)
    if hypothetical is None:
        hypothetical = generate_hypothetical(query)

    lines = ["## ENGINEERED SEARCH STRATEGY\n"]

    lines.append("### Precision Queries (try in order until you get good results):")
    for i, q in enumerate(operator_queries, 1):
        lines.append(f"  {i}. `{q}`")

    lines.append(f"\n### Multi-Angle Searches:")
    lines.append(f"  Direct:    `{angles['direct']}`")
    lines.append(f"  Deal/Best: `{angles['deal']}`")
    lines.append(f"  Authority: `{angles['authority']}`")

    if hypothetical:
        lines.append(f"\n### Hypothetical Target (search for the answer shape):")
        lines.append(f"  `{hypothetical}`")

    sources = []
    for intent in intents[:2]:
        sources.extend(SOURCE_MAP.get(intent, [])[:2])
    if sources:
        lines.append(f"\n### Best Sources for This Query Type:")
        for s in sources[:4]:
            lines.append(f"  → {s}")

    if temporal:
        lines.append(f"\n### Recency: Add Google Tools → Past Year filter. Results must be from {year - 1} or {year}.")

    lines.append("\n### Google Operator Reference (use as needed):")
    lines.append('  site:X      — restrict to one site')
    lines.append('  "phrase"    — exact match')
    lines.append('  -word       — exclude word')
    lines.append('  after:YYYY  — results from date')
    lines.append('  intitle:X   — keyword in page title')
    lines.append('  A..B        — number range')
    lines.append("")

    return "\n".join(lines)
