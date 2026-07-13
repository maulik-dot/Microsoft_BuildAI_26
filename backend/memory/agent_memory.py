import copy
import json
import os
import re

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "../../../agent_memory.json")

DEFAULT_MEMORY = {
    "research": {
        "works": [],
        "blocked": [],
        "tips": [],
        "page_flows": [],
    }
}

BLOCKED_PATTERNS = [
    "bot detection", "blocked", "captcha", "err_http2", "access denied",
    "403", "cloudflare", "unusual traffic", "verify you are human",
]


def _normalize(memory: dict) -> dict:
    if not isinstance(memory, dict):
        return copy.deepcopy(DEFAULT_MEMORY)

    memory.setdefault("research", {"works": [], "blocked": [], "tips": [], "page_flows": []})
    research = memory["research"]
    research.setdefault("works", [])
    research.setdefault("blocked", [])
    research.setdefault("tips", [])
    research.setdefault("page_flows", [])

    # Fold older domain-specific buckets into the generic research bucket.
    for key, bucket in list(memory.items()):
        if key == "research" or not isinstance(bucket, dict):
            continue
        for field in ("works", "blocked", "tips"):
            for item in bucket.get(field, []) or []:
                if item not in research[field]:
                    research[field].append(item)

    return memory


def _load() -> dict:
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE) as f:
            return _normalize(json.load(f))
    return copy.deepcopy(DEFAULT_MEMORY)


def _save(memory: dict):
    memory = _normalize(memory)
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)


def get_context(task_type: str) -> str:
    """Return a memory block to inject at the top of every task prompt."""
    memory = _load()
    bucket = memory.get(task_type) or memory.get("research", {})

    works = bucket.get("works", [])
    blocked = bucket.get("blocked", [])
    tips = bucket.get("tips", [])

    lines = ["AGENT MEMORY (learned from previous browser runs):"]

    if works:
        lines.append(f"✅ Sites that worked: {', '.join(works[:6])}")
    if blocked:
        lines.append(f"❌ Sites to avoid: {', '.join(blocked[:6])}")
    if tips:
        lines.append("💡 Tips:")
        for tip in tips[:6]:
            lines.append(f"   - {tip}")

    lines.append("Use this knowledge to inspect the page, infer the flow, and adapt quickly.\n")
    return "\n".join(lines)


def _domains_from_text(text: str) -> list[str]:
    domains = re.findall(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})(?:/[^\s]*)?', text)
    return list(set(d.lower() for d in domains if "." in d and len(d) > 5))


def update(task_type: str, result_text: str, success: bool):
    """Parse the result and update memory with new learnings."""
    memory = _load()
    if task_type not in memory:
        memory[task_type] = {"works": [], "blocked": [], "tips": [], "page_flows": []}

    bucket = memory[task_type]
    domains = _domains_from_text(result_text)
    result_lower = result_text.lower()

    for domain in domains:
        is_blocked = any(
            pattern in result_lower
            for pattern in BLOCKED_PATTERNS
            if domain in result_lower[max(0, result_lower.find(domain) - 200):result_lower.find(domain) + 200]
        )

        if is_blocked:
            if domain not in bucket["blocked"]:
                bucket["blocked"].append(domain)
            if domain in bucket["works"]:
                bucket["works"].remove(domain)
        elif success and domain not in bucket["blocked"] and domain not in bucket["works"]:
            bucket["works"].append(domain)

    _save(memory)


def add_tip(task_type: str, tip: str):
    """Manually add a tip for a task type."""
    memory = _load()
    if task_type not in memory:
        memory[task_type] = {"works": [], "blocked": [], "tips": [], "page_flows": []}
    if tip not in memory[task_type]["tips"]:
        memory[task_type]["tips"].append(tip)
    _save(memory)


def mark_blocked(task_type: str, domain: str):
    """Mark a site as blocked for a task type."""
    memory = _load()
    if task_type not in memory:
        memory[task_type] = {"works": [], "blocked": [], "tips": [], "page_flows": []}
    bucket = memory[task_type]
    if domain not in bucket["blocked"]:
        bucket["blocked"].append(domain)
    if domain in bucket["works"]:
        bucket["works"].remove(domain)
    _save(memory)


def mark_works(task_type: str, domain: str):
    """Mark a site as working for a task type."""
    memory = _load()
    if task_type not in memory:
        memory[task_type] = {"works": [], "blocked": [], "tips": [], "page_flows": []}
    bucket = memory[task_type]
    if domain not in bucket["works"]:
        bucket["works"].insert(0, domain)
    if domain in bucket["blocked"]:
        bucket["blocked"].remove(domain)
    _save(memory)


# --- General research memory (not tied to a task type) ---

GENERAL_MEMORY_FILE = os.path.join(os.path.dirname(__file__), "../../../general_memory.json")

DEFAULT_GENERAL = {
    "successful_sources": {},
    "blocked_sites": [],
    "search_patterns": [],
    "past_queries": [],
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
    """Return relevant memory context for a general browser query."""
    data = _load_general()

    top_sources = sorted(
        data.get("successful_sources", {}).items(),
        key=lambda x: x[1],
        reverse=True,
    )[:8]

    blocked = data.get("blocked_sites", [])
    patterns = data.get("search_patterns", [])[-5:]
    past = data.get("past_queries", [])[-5:]

    lines = ["## AGENT MEMORY (learned from previous browser sessions)"]
    if top_sources:
        lines.append("✅ Most reliable sources from past browser sessions:")
        for domain, count in top_sources:
            lines.append(f"   - {domain} (used successfully {count}x)")
    if blocked:
        lines.append(f"❌ Sites that block browser access: {', '.join(blocked)}")
    if patterns:
        lines.append("💡 Effective search query patterns:")
        for p in patterns:
            lines.append(f"   - {p}")
    if past:
        lines.append("📋 Recent browser context:")
        for q in past:
            lines.append(f"   - {q}")

    return "\n".join(lines) + "\n"


def update_general(query: str, result: str, success: bool):
    """Update general memory after a browser run."""
    data = _load_general()

    domains = _domains_from_text(result)
    if success:
        sources = data.setdefault("successful_sources", {})
        for d in domains[:5]:
            sources[d] = sources.get(d, 0) + 1

    result_lower = result.lower()
    for d in domains:
        if any(p in result_lower for p in BLOCKED_PATTERNS):
            blocked = data.setdefault("blocked_sites", [])
            if d not in blocked:
                blocked.append(d)

    past = data.setdefault("past_queries", [])
    summary = f"{query[:80]}{'...' if len(query) > 80 else ''} → {'success' if success else 'failed'}"
    past.append(summary)
    data["past_queries"] = past[-20:]

    _save_general(data)
