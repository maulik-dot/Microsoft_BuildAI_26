import json
import re
import os

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "../../../agent_memory.json")

# Default memory — pre-seeded with what we already know
DEFAULT_MEMORY = {
    "travel": {
        "works": ["ixigo.com"],
        "blocked": ["makemytrip.com", "kayak.com", "skyscanner.com", "google.com/travel"],
        "tips": [
            "ixigo.com/flights: enter From/To city names with dropdown selection, pick date from calendar, click Search",
            "ixigo.com/hotels: enter city, check-in/check-out, click Search, sort by Price Low to High",
            "Flight results take 3-5s to load — scroll down to see non-stop options",
            "Expand flight cards to see exact departure/arrival times",
        ],
    },
    "jobs": {
        "works": ["naukri.com"],
        "blocked": ["linkedin.com"],
        "tips": [
            "naukri.com: search bar at top with role + location fields, press Enter or click Search",
            "Sort results by Date to get freshest listings",
            "Click job title to open full JD in a side panel — apply button is there",
            "Easy Apply jobs show a lightning bolt icon",
        ],
    },
    "hackathon": {
        "works": ["devfolio.co/hackathons", "unstop.com/hackathons"],
        "blocked": [],
        "tips": [
            "devfolio.co/hackathons: scroll down slowly — cards lazy-load as you scroll",
            "Click each hackathon card to open detail page with full prize breakdown and eligibility",
            "devfolio detail page has tabs: About, Prizes, Schedule, FAQs — check all",
            "unstop.com: filter by Hackathon type, sort by Prize Money for best results",
        ],
    },
    "price_monitor": {
        "works": ["flipkart.com", "amazon.in"],
        "blocked": [],
        "tips": [
            "flipkart: search bar top center, product page has 'Available Offers' section with bank deals",
            "amazon.in: product page shows 'New from ₹X' for all seller prices — click to compare",
            "Both sites show EMI options below the main price",
            "Check 'Other sellers' section for cheaper alternatives on the same listing",
        ],
    },
}

# Patterns that indicate a site blocked the agent
BLOCKED_PATTERNS = [
    "bot detection", "blocked", "captcha", "ERR_HTTP2", "access denied",
    "403", "cloudflare", "unusual traffic", "verify you are human",
]


def _load() -> dict:
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE) as f:
            return json.load(f)
    return DEFAULT_MEMORY.copy()


def _save(memory: dict):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)


def get_context(task_type: str) -> str:
    """Return a memory block to inject at the top of every task prompt."""
    memory = _load()
    m = memory.get(task_type, {})

    works = m.get("works", [])
    blocked = m.get("blocked", [])
    tips = m.get("tips", [])

    lines = ["AGENT MEMORY (learned from previous runs):"]

    if works:
        lines.append(f"✅ Sites that work well: {', '.join(works)}")
    if blocked:
        lines.append(f"❌ Avoid these sites (bot detection/errors): {', '.join(blocked)}")
    if tips:
        lines.append("💡 Tips:")
        for tip in tips:
            lines.append(f"   - {tip}")

    lines.append("Use this knowledge to pick the best sites and approach first.\n")
    return "\n".join(lines)


def update(task_type: str, result_text: str, success: bool):
    """Parse the result and update memory with new learnings."""
    memory = _load()
    if task_type not in memory:
        memory[task_type] = {"works": [], "blocked": [], "tips": []}

    m = memory[task_type]

    # Extract domains mentioned in the result
    domains = re.findall(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})(?:/[^\s]*)?', result_text)
    domains = list(set(d.lower() for d in domains if "." in d and len(d) > 5))

    result_lower = result_text.lower()

    for domain in domains:
        # Check if this domain was associated with a block/error
        is_blocked = any(pattern in result_lower for pattern in BLOCKED_PATTERNS
                         if domain in result_lower[max(0, result_lower.find(domain)-200):result_lower.find(domain)+200])

        if is_blocked:
            if domain not in m["blocked"]:
                m["blocked"].append(domain)
            if domain in m["works"]:
                m["works"].remove(domain)
        elif success and domain not in m["blocked"] and domain not in m["works"]:
            m["works"].append(domain)

    _save(memory)


def add_tip(task_type: str, tip: str):
    """Manually add a tip for a task type."""
    memory = _load()
    if task_type not in memory:
        memory[task_type] = {"works": [], "blocked": [], "tips": []}
    if tip not in memory[task_type]["tips"]:
        memory[task_type]["tips"].append(tip)
    _save(memory)


def mark_blocked(task_type: str, domain: str):
    """Mark a site as blocked for a task type."""
    memory = _load()
    if task_type not in memory:
        memory[task_type] = {"works": [], "blocked": [], "tips": []}
    m = memory[task_type]
    if domain not in m["blocked"]:
        m["blocked"].append(domain)
    if domain in m["works"]:
        m["works"].remove(domain)
    _save(memory)


def mark_works(task_type: str, domain: str):
    """Mark a site as working for a task type."""
    memory = _load()
    if task_type not in memory:
        memory[task_type] = {"works": [], "blocked": [], "tips": []}
    m = memory[task_type]
    if domain not in m["works"]:
        m["works"].insert(0, domain)
    if domain in m["blocked"]:
        m["blocked"].remove(domain)
    _save(memory)


# --- General research memory (not tied to a task type) ---

GENERAL_MEMORY_FILE = os.path.join(os.path.dirname(__file__), "../../../general_memory.json")

DEFAULT_GENERAL = {
    "successful_sources": {},   # domain -> how many times it gave good results
    "blocked_sites": [],        # sites that consistently block
    "search_patterns": [],      # effective Google search query patterns learned
    "past_queries": [],         # last 20 queries + brief outcome (for context)
}


def _load_general() -> dict:
    if os.path.exists(GENERAL_MEMORY_FILE):
        with open(GENERAL_MEMORY_FILE) as f:
            return json.load(f)
    return DEFAULT_GENERAL.copy()


def _save_general(data: dict):
    with open(GENERAL_MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_general_context(query: str) -> str:
    """Return relevant memory context for a general research query."""
    data = _load_general()

    top_sources = sorted(
        data.get("successful_sources", {}).items(),
        key=lambda x: x[1], reverse=True
    )[:8]

    blocked = data.get("blocked_sites", [])
    patterns = data.get("search_patterns", [])[-5:]
    past = data.get("past_queries", [])[-5:]

    lines = ["## AGENT MEMORY (learned from previous research sessions)"]
    if top_sources:
        lines.append("✅ Most reliable sources from past research:")
        for domain, count in top_sources:
            lines.append(f"   - {domain} (used successfully {count}x)")
    if blocked:
        lines.append(f"❌ Sites that block research access: {', '.join(blocked)}")
    if patterns:
        lines.append("💡 Effective search query patterns:")
        for p in patterns:
            lines.append(f"   - {p}")
    if past:
        lines.append("📋 Recent research context:")
        for q in past:
            lines.append(f"   - {q}")

    return "\n".join(lines) + "\n"


def update_general(query: str, result: str, success: bool):
    """Update general memory after a research run."""
    data = _load_general()

    # Extract domains from result
    domains = re.findall(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})', result)
    domains = list(set(d.lower() for d in domains if len(d) > 5))

    if success:
        sources = data.setdefault("successful_sources", {})
        for d in domains[:5]:  # top 5 domains from result
            sources[d] = sources.get(d, 0) + 1

    # Track blocked sites
    result_lower = result.lower()
    for d in domains:
        if any(p in result_lower for p in BLOCKED_PATTERNS):
            blocked = data.setdefault("blocked_sites", [])
            if d not in blocked:
                blocked.append(d)

    # Store query summary
    past = data.setdefault("past_queries", [])
    summary = f"{query[:80]}{'...' if len(query) > 80 else ''} → {'success' if success else 'failed'}"
    past.append(summary)
    data["past_queries"] = past[-20:]  # keep last 20

    _save_general(data)
