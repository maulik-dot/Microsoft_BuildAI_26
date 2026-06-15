"""
Universal Comparison Agent — fully self-learning, zero hardcoded sites.

The agent discovers sources via Google, tries them, remembers what worked
and what failed. Every run makes it smarter. No human-curated lists.

Learning loop:
1. Read memory → know which sites worked before for similar queries
2. Search Google → discover fresh sources for this specific query
3. Try sources → record success/failure in memory after each attempt
4. Next run → memory already knows, agent is faster and smarter
"""

from backend.tools.browser import run_deep_task
from backend.tools.planner import _call_llm
from backend.memory.agent_memory import (
    get_general_context, update_general,
    _load_general, _save_general
)


def _record_site_outcome(domain: str, worked: bool):
    """Update general memory with site experience."""
    data = _load_general()
    sources = data.setdefault("successful_sources", {})
    blocked = data.setdefault("blocked_sites", [])

    if worked:
        sources[domain] = sources.get(domain, 0) + 1
        if domain in blocked:
            blocked.remove(domain)
    else:
        if domain not in blocked:
            blocked.append(domain)
        sources.pop(domain, None)

    _save_general(data)


def _get_memory_context_for_comparison(query: str) -> str:
    """
    Build context from what the agent has already learned.
    Prioritises sites that worked most often in past runs.
    """
    data = _load_general()
    sources = data.get("successful_sources", {})
    blocked = data.get("blocked_sites", [])

    if not sources and not blocked:
        return ""  # No memory yet — agent will learn from scratch

    # Sort by success count
    top = sorted(sources.items(), key=lambda x: x[1], reverse=True)[:5]

    lines = ["## WHAT I LEARNED FROM PREVIOUS RESEARCH SESSIONS"]
    if top:
        lines.append("Sites that worked well in past searches (most reliable first):")
        for domain, count in top:
            lines.append(f"  ✅ {domain} — worked {count} time(s)")
    if blocked:
        lines.append("Sites that blocked me or failed — skip immediately:")
        for domain in blocked[:8]:
            lines.append(f"  ❌ {domain}")
    lines.append("Use this knowledge to pick your starting sites, but stay open to discovering new ones via Google.\n")
    return "\n".join(lines)


async def run_comparison(query: str, task_id: str = "") -> dict:
    """
    Self-learning comparison: Google-first discovery + memory-informed site selection.
    After every run, updates memory with what worked.
    """
    from datetime import datetime
    current_year = datetime.now().year

    memory_ctx = get_general_context(query)
    learned_ctx = _get_memory_context_for_comparison(query)

    task = f"""{memory_ctx}
{learned_ctx}

COMPARISON QUERY: {query}

YOUR TASK — find the best result by comparing multiple sources:

STEP 1 — DISCOVER SOURCES VIA GOOGLE:
1. Go to https://www.google.com
2. Search for: {query} best price {current_year}
3. Look at the top 5 search results — these are the sites Google trusts most
4. Also look at Google Shopping results if visible
5. Note the top 3-4 distinct domains from the results

STEP 2 — TRY EACH SOURCE (max 8-10 steps per site):
For each site discovered:
- Navigate to it and search for the specific item/query
- If it BLOCKS you (CAPTCHA, login wall, bot detection) within 3 steps → STOP, move to next site, and remember it failed
- If it WORKS:
  1. For the top 2 matching products under the budget/limit, you MUST click on the product to navigate to its specific details page.
  2. On the product details page, extract: the exact product name, price/option, rating, the direct product page URL (from the browser's address bar), and the primary product image URL (the direct source URL of the main product image).
  3. Do NOT just copy the homepage URL (like amazon.in). You MUST extract the specific direct product page link and direct product image URL.
- Keep going until you have data from at least 2 working sources

STEP 3 — LEARN AND REPORT:
After trying sites, in your FINAL RESULT include:
- A comparison table with all working sources side by side, including product name, price, rating, direct purchase page link, and product image URL
- BEST VALUE = [site] at [price/option] because [reason]
- Direct purchase page links and product image URLs to each result found
- Note any sites that were blocked (so future searches skip them)

IMPORTANT RULES:
- Always start with Google to discover sources — don't assume which sites are best
- If the first site fails, try the next Google result immediately
- Never spend more than 10 steps on a single site
- A site that loads slowly but eventually works is fine — a site that shows CAPTCHA/login wall is not
- The goal is finding the BEST result, not just the first result"""

    result = await run_deep_task(task, task_type="research", task_id=task_id, max_steps=35, original_query=query)

    # Learn from this run — extract which sites appeared in the result
    if result:
        import re
        # Sites mentioned positively (in tables, URLs, recommendations)
        found_domains = re.findall(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})(?:/[^\s\)]*)?', result)
        failed_signals = ["blocked", "captcha", "login wall", "could not access", "unable to reach"]

        for domain in set(found_domains):
            if len(domain) < 5:
                continue
            # Check if this domain is mentioned near a failure signal
            idx = result.lower().find(domain.lower())
            context_around = result.lower()[max(0, idx-100):idx+100]
            failed = any(sig in context_around for sig in failed_signals)
            _record_site_outcome(domain, worked=not failed)

    update_general(query, result, success=bool(result and len(result) > 100))
    return {"query": query, "result": result, "task_type": "comparison"}
