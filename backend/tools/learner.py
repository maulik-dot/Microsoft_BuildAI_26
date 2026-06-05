"""
Post-Run Learner — extracts structured lessons from every completed agent run.

After each task, this module analyses:
- Which sites were visited and whether they worked
- How many steps it took to get results from each site
- What search queries produced good results
- What obstacles were hit and how they were resolved
- Navigation patterns that succeeded on specific sites

All lessons are stored in web_knowledge.json — a growing knowledge base
that makes every future run smarter.

The compounding effect: after 100 runs the agent knows the web like
a professional researcher who has been at it for months.
"""

import json
import os
import re
from datetime import datetime
from backend.tools.planner import _call_llm

KNOWLEDGE_FILE = os.path.join(os.path.dirname(__file__), "../../../web_knowledge.json")


# ── Knowledge Schema ──────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(KNOWLEDGE_FILE):
        try:
            with open(KNOWLEDGE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "sites": {},           # domain → {navigation, tips, avg_steps, success_count, fail_count}
        "search_patterns": {}, # query_type → [effective search templates]
        "obstacle_solutions": [], # [{obstacle, solution, site}]
        "domain_shortcuts": {},   # query category → [best starting sites in order]
        "last_updated": None,
    }


def _save(knowledge: dict):
    knowledge["last_updated"] = datetime.now().isoformat()
    try:
        with open(KNOWLEDGE_FILE, "w") as f:
            json.dump(knowledge, f, indent=2)
    except Exception:
        pass


# ── Main Learning Entry Point ─────────────────────────────────────────────────

def learn_from_run(query: str, steps: list[dict], result: str, success: bool):
    """
    Called after every task completes. Extracts lessons and updates knowledge base.

    steps: list of {step, url, title, action, detail, description}
    result: the final answer text
    success: whether the task produced a good result
    """
    if not steps and not result:
        return  # Nothing to learn from

    knowledge = _load()

    # 1. Extract which sites were visited and their outcomes
    _learn_site_performance(knowledge, steps, result, success)

    # 2. Extract effective search queries
    _learn_search_patterns(knowledge, query, steps, result, success)

    # 3. Extract navigation patterns for successful sites
    if success and steps:
        _learn_navigation_patterns(knowledge, steps, result)

    # 4. Extract obstacle solutions
    _learn_obstacle_solutions(knowledge, steps, result)

    # 5. Update domain shortcuts (best sites for this type of query)
    if success:
        _update_domain_shortcuts(knowledge, query, steps)

    _save(knowledge)


def _learn_site_performance(knowledge: dict, steps: list, result: str, success: bool):
    """Track which sites worked and how many steps they needed."""
    if not steps:
        return

    sites_node = knowledge.setdefault("sites", {})

    # Group steps by domain
    domain_steps: dict[str, list] = {}
    for step in steps:
        url = step.get("url", "")
        if not url:
            continue
        try:
            domain = re.sub(r'^(https?://)?(www\.)?', '', url).split('/')[0].split('?')[0]
            if domain and '.' in domain and len(domain) > 4:
                domain_steps.setdefault(domain, []).append(step)
        except Exception:
            pass

    result_lower = (result or "").lower()
    failure_signals = ["blocked", "captcha", "could not", "unable", "failed", "error", "not found"]

    for domain, domain_step_list in domain_steps.items():
        site = sites_node.setdefault(domain, {
            "success_count": 0, "fail_count": 0,
            "avg_steps": 0, "total_steps": 0, "runs": 0,
            "tips": [], "navigation_hint": "", "last_seen": None,
        })

        site["runs"] = site.get("runs", 0) + 1
        site["total_steps"] = site.get("total_steps", 0) + len(domain_step_list)
        site["avg_steps"] = round(site["total_steps"] / site["runs"])
        site["last_seen"] = datetime.now().strftime("%Y-%m-%d")

        # Check if this site contributed to success or failure
        # Look for domain near failure signals in result
        domain_in_result = domain in result_lower
        near_failure = False
        if domain_in_result:
            idx = result_lower.find(domain)
            context = result_lower[max(0, idx - 150):idx + 150]
            near_failure = any(sig in context for sig in failure_signals)

        if success and domain_in_result and not near_failure:
            site["success_count"] = site.get("success_count", 0) + 1
        elif near_failure:
            site["fail_count"] = site.get("fail_count", 0) + 1


def _learn_search_patterns(knowledge: dict, query: str, steps: list, result: str, success: bool):
    """Extract effective Google search queries from successful runs."""
    if not success or not steps:
        return

    patterns = knowledge.setdefault("search_patterns", {})

    # Find Google search steps
    google_searches = []
    for step in steps:
        url = step.get("url", "")
        if "google.com/search" in url or "google.com/search" in step.get("detail", ""):
            # Extract the search query from URL
            match = re.search(r'[?&]q=([^&]+)', url)
            if match:
                search_q = match.group(1).replace('+', ' ').replace('%20', ' ')
                google_searches.append(search_q)
        # Also capture typed search queries from action details
        if step.get("action") in ("type", "fill", "input") and step.get("description"):
            desc = step["description"]
            if "search" in desc.lower() and len(desc) > 10:
                google_searches.append(desc[:100])

    if not google_searches:
        return

    # Use LLM to extract the query intent category
    category = _call_llm(f"""What is the category of this search query in 2-3 words?
Query: "{query}"
Return only 2-3 words, e.g. "flight price search", "product comparison", "job search", "tutorial search".""",
        task_type="planning")

    if category:
        category = category.strip().lower()[:50]
        cat_patterns = patterns.setdefault(category, [])
        for s in google_searches[:2]:
            if s not in cat_patterns and len(s) > 5:
                cat_patterns.insert(0, s)
        patterns[category] = cat_patterns[:5]  # keep top 5 per category


def _learn_navigation_patterns(knowledge: dict, steps: list, result: str):
    """Extract step-by-step navigation patterns for sites that worked."""
    if not steps or len(steps) < 3:
        return

    sites_node = knowledge.setdefault("sites", {})

    # Group steps by domain and extract navigation sequence
    domain_sequences: dict[str, list[str]] = {}
    for step in steps:
        url = step.get("url", "")
        desc = step.get("description", "")
        action = step.get("action", "")
        if not url or not desc:
            continue
        try:
            domain = re.sub(r'^(https?://)?(www\.)?', '', url).split('/')[0].split('?')[0]
            if domain and '.' in domain:
                domain_sequences.setdefault(domain, []).append(f"{action}: {desc[:80]}")
        except Exception:
            pass

    for domain, sequence in domain_sequences.items():
        if len(sequence) < 2:
            continue
        site = sites_node.setdefault(domain, {
            "success_count": 0, "fail_count": 0,
            "avg_steps": 0, "total_steps": 0, "runs": 0,
            "tips": [], "navigation_hint": "", "last_seen": None,
        })

        # Use LLM to summarise the navigation sequence into a useful hint
        seq_text = "\n".join(sequence[:8])
        hint = _call_llm(f"""Summarise these browser steps for {domain} into ONE concise navigation tip (max 120 chars).
Focus on what buttons/fields to interact with in what order.

Steps:
{seq_text}

Return only the tip, e.g. "Enter city in From/To fields, wait for dropdown, select date, click blue Search button" """,
            task_type="planning")

        if hint and len(hint) > 10:
            site["navigation_hint"] = hint.strip()[:150]


def _learn_obstacle_solutions(knowledge: dict, steps: list, result: str):
    """Record how obstacles were resolved."""
    if not result:
        return

    obstacles = knowledge.setdefault("obstacle_solutions", [])
    result_lower = result.lower()

    obstacle_keywords = {
        "captcha": "CAPTCHA detected",
        "login wall": "Login wall encountered",
        "bot detection": "Bot detection triggered",
        "popup": "Popup/modal appeared",
        "slow loading": "Page slow to load",
        "no results": "Search returned no results",
    }

    for keyword, label in obstacle_keywords.items():
        if keyword in result_lower:
            # Find what the agent did next
            idx = result_lower.find(keyword)
            context_after = result[idx:idx+300]

            # Only record if we found a solution (not just a failure)
            if any(w in result_lower[idx:] for w in ["instead", "navigated", "tried", "found", "switched"]):
                entry = {
                    "obstacle": label,
                    "context": context_after[:200],
                    "date": datetime.now().strftime("%Y-%m-%d"),
                }
                # Don't add duplicates
                if not any(o.get("obstacle") == label and o.get("context", "")[:50] == entry["context"][:50]
                           for o in obstacles[-10:]):
                    obstacles.append(entry)
                    obstacles[:] = obstacles[-20:]  # keep last 20


def _update_domain_shortcuts(knowledge: dict, query: str, steps: list):
    """Update which sites are fastest for which query types."""
    shortcuts = knowledge.setdefault("domain_shortcuts", {})

    # Get domains that appeared in steps
    domains = []
    for step in steps:
        url = step.get("url", "")
        if url:
            try:
                domain = re.sub(r'^(https?://)?(www\.)?', '', url).split('/')[0].split('?')[0]
                if domain and '.' in domain and domain not in domains:
                    domains.append(domain)
            except Exception:
                pass

    if not domains:
        return

    # Simple category detection from query
    q = query.lower()
    if any(w in q for w in ["flight", "hotel", "travel", "trip"]):
        cat = "travel"
    elif any(w in q for w in ["job", "career", "salary", "hiring"]):
        cat = "jobs"
    elif any(w in q for w in ["price", "buy", "cost", "cheap", "deal"]):
        cat = "price_comparison"
    elif any(w in q for w in ["hackathon", "competition", "contest"]):
        cat = "hackathons"
    elif any(w in q for w in ["course", "tutorial", "learn"]):
        cat = "learning"
    elif any(w in q for w in ["news", "latest", "recent", "today"]):
        cat = "news"
    else:
        cat = "general"

    existing = shortcuts.get(cat, [])
    for domain in domains[:3]:
        if domain in existing:
            existing.remove(domain)
        existing.insert(0, domain)  # most recently successful goes first
    shortcuts[cat] = existing[:5]


# ── Context Injection ─────────────────────────────────────────────────────────

def get_learned_context(query: str) -> str:
    """
    Return the most relevant learned knowledge for a given query.
    Injected into agent context before each run.
    """
    knowledge = _load()
    lines = []

    # Relevant domain shortcuts
    shortcuts = knowledge.get("domain_shortcuts", {})
    q = query.lower()
    relevant_cats = []
    if any(w in q for w in ["flight", "hotel", "travel", "trip"]): relevant_cats.append("travel")
    if any(w in q for w in ["job", "career"]): relevant_cats.append("jobs")
    if any(w in q for w in ["price", "buy", "cost", "cheap"]): relevant_cats.append("price_comparison")
    if any(w in q for w in ["course", "tutorial", "learn"]): relevant_cats.append("learning")
    if any(w in q for w in ["news", "latest", "recent"]): relevant_cats.append("news")
    if not relevant_cats: relevant_cats.append("general")

    for cat in relevant_cats:
        sites = shortcuts.get(cat, [])
        if sites:
            lines.append(f"## LEARNED: Best sites for {cat} queries")
            for s in sites[:3]:
                lines.append(f"  → {s}")

    # Navigation hints for known sites
    sites_node = knowledge.get("sites", {})
    high_confidence = [(d, s) for d, s in sites_node.items()
                       if s.get("success_count", 0) >= 2 and s.get("navigation_hint")]
    high_confidence.sort(key=lambda x: x[1].get("success_count", 0), reverse=True)

    if high_confidence:
        lines.append("\n## LEARNED: How to navigate these sites")
        for domain, site in high_confidence[:4]:
            hint = site.get("navigation_hint", "")
            if hint:
                avg = site.get("avg_steps", "?")
                lines.append(f"  {domain} (~{avg} steps): {hint}")

    # Search patterns
    patterns = knowledge.get("search_patterns", {})
    for cat in relevant_cats:
        p = patterns.get(cat, [])
        if p:
            lines.append(f"\n## LEARNED: Effective search queries for {cat}")
            for pattern in p[:2]:
                lines.append(f"  → \"{pattern}\"")

    return "\n".join(lines) if lines else ""
