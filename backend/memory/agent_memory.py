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
            "ixigo.com works well for Indian flights and hotels",
            "search flights at ixigo.com/flights, hotels at ixigo.com/hotels",
        ],
    },
    "jobs": {
        "works": ["naukri.com", "indeed.co.in"],
        "blocked": ["linkedin.com"],
        "tips": [
            "naukri.com has a search bar at top — type role then location",
            "indeed.co.in is accessible and shows salary ranges",
        ],
    },
    "hackathon": {
        "works": ["devfolio.co/hackathons", "unstop.com/hackathons"],
        "blocked": [],
        "tips": [
            "devfolio.co/hackathons lists cards — scroll down to see more",
            "each card shows name, dates, prize, and a register button",
        ],
    },
    "price_monitor": {
        "works": ["flipkart.com", "amazon.in"],
        "blocked": [],
        "tips": [
            "flipkart search bar is at top center",
            "amazon.in shows prices clearly on product listing pages",
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
        m["works"].insert(0, domain)  # insert at front — most recently confirmed working
    if domain in m["blocked"]:
        m["blocked"].remove(domain)
    _save(memory)
