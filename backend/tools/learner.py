"""
Post-Run Learner — extracts reusable web knowledge from every agent run.

The learner stores two kinds of memory:
- Site memory: what worked on a specific domain
- Web memory: reusable page-type patterns that apply across the web

This keeps the agent general-purpose instead of domain-specific.
"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime

from backend.tools.planner import _call_llm

KNOWLEDGE_FILE = os.path.join(os.path.dirname(__file__), "../../../web_knowledge.json")

IGNORED_DOMAINS = {
    "google.com", "google.co.in", "google.co.uk", "google.ca", "google.com.au",
    "bing.com", "duckduckgo.com", "yahoo.com", "search.yahoo.com", "baidu.com", "yandex.com",
}

PAGE_TYPES = (
    "search_results",
    "detail_page",
    "filter_panel",
    "form_page",
    "list_page",
    "pagination",
    "login_wall",
    "modal",
    "checkout",
    "table",
    "article",
    "home_page",
    "unknown",
)

DEFAULT_KNOWLEDGE = {
    "sites": {},
    "web_patterns": {},
    "query_patterns": {},
    "obstacle_solutions": [],
    "last_updated": None,
}


def _blank_web_bucket() -> dict:
    return {"count": 0, "hints": [], "flows": [], "examples": []}


def _blank_site_entry() -> dict:
    return {
        "success_count": 0,
        "fail_count": 0,
        "avg_steps": 0,
        "total_steps": 0,
        "runs": 0,
        "tips": [],
        "navigation_hint": "",
        "page_flows": {},
        "last_seen": None,
    }


def _load() -> dict:
    if os.path.exists(KNOWLEDGE_FILE):
        try:
            with open(KNOWLEDGE_FILE) as f:
                data = json.load(f)
        except Exception:
            data = copy.deepcopy(DEFAULT_KNOWLEDGE)
    else:
        data = copy.deepcopy(DEFAULT_KNOWLEDGE)

    return _normalize_schema(data)


def _normalize_schema(data: dict) -> dict:
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_KNOWLEDGE)

    # Migrate older field names into the new schema.
    if "search_patterns" in data and "query_patterns" not in data:
        data["query_patterns"] = data.pop("search_patterns")

    data.setdefault("sites", {})
    data.setdefault("web_patterns", {})
    data.setdefault("query_patterns", {})
    data.setdefault("obstacle_solutions", [])
    data.setdefault("last_updated", None)

    for page_type in PAGE_TYPES:
        data["web_patterns"].setdefault(page_type, _blank_web_bucket())

    for domain, site in list(data["sites"].items()):
        if not isinstance(site, dict):
            data["sites"][domain] = _blank_site_entry()
            continue
        site.setdefault("success_count", 0)
        site.setdefault("fail_count", 0)
        site.setdefault("avg_steps", 0)
        site.setdefault("total_steps", 0)
        site.setdefault("runs", 0)
        site.setdefault("tips", [])
        site.setdefault("navigation_hint", "")
        site.setdefault("page_flows", {})
        site.setdefault("last_seen", None)

    # If older records exist, fold them into the new generic structure.
    _migrate_legacy_site_memory(data)
    return data


def _migrate_legacy_site_memory(data: dict) -> None:
    legacy_domains = {"travel", "jobs", "hackathon", "price_monitor"}
    if not any(k in data for k in legacy_domains):
        return

    target = data["sites"].setdefault("_legacy_web", _blank_site_entry())
    for legacy_key in legacy_domains:
        legacy = data.get(legacy_key, {})
        if not isinstance(legacy, dict):
            continue
        for key in ("works", "blocked", "tips"):
            for item in legacy.get(key, []) or []:
                _append_unique(target.setdefault("tips" if key == "tips" else key, []), item, limit=20)


def _save(knowledge: dict):
    knowledge = _normalize_schema(knowledge)
    knowledge["last_updated"] = datetime.now().isoformat()
    try:
        os.makedirs(os.path.dirname(KNOWLEDGE_FILE), exist_ok=True)
        with open(KNOWLEDGE_FILE, "w") as f:
            json.dump(knowledge, f, indent=2)
    except Exception:
        pass


def _normalize_domain(url: str) -> str:
    if not url:
        return ""
    domain = re.sub(r"^(https?://)?(www\.)?", "", url).split("/")[0].split("?")[0].lower()
    return domain


def _append_unique(items: list, value, limit: int | None = None):
    if value and value not in items:
        items.append(value)
    if limit is not None:
        del items[:-limit]


def _step_text(step: dict) -> str:
    action = step.get("action", "")
    detail = step.get("detail", "")
    description = step.get("description", "")
    parts = [p for p in [action, detail, description] if p]
    return " | ".join(parts).strip()


def _infer_page_type(step: dict) -> str:
    text = " ".join(
        str(step.get(field, "")) for field in ("url", "title", "action", "detail", "description")
    ).lower()

    if any(w in text for w in ("captcha", "verify you are human", "access denied", "blocked", "signin", "sign in", "log in", "login")):
        return "login_wall"
    if any(w in text for w in ("checkout", "cart", "payment", "buy now", "order summary")):
        return "checkout"
    if any(w in text for w in ("filter", "sort", "refine", "facets", "toggle")):
        return "filter_panel"
    if any(w in text for w in ("load more", "pagination", "next page", "page 2", "scroll for more")):
        return "pagination"
    if any(w in text for w in ("table", "grid", "rows", "columns")):
        return "table"
    if any(w in text for w in ("results for", "search results", "showing results", "/search", "search?")):
        return "search_results"
    if any(w in text for w in ("detail", "overview", "full description", "product page", "job description", "about this")):
        return "detail_page"
    if any(w in text for w in ("form", "field", "input", "submit", "apply now", "sign up")):
        return "form_page"
    if any(w in text for w in ("home", "homepage", "landing page")):
        return "home_page"
    if any(w in text for w in ("popup", "modal", "dialog", "cookie banner")):
        return "modal"
    if any(w in text for w in ("article", "blog", "post", "news")):
        return "article"
    return "unknown"


def _infer_query_page_types(query: str) -> list[str]:
    q = query.lower()
    types = []
    if any(w in q for w in ("compare", "price", "cost", "buy", "deal", "cheapest", "under", "amazon", "flipkart")):
        types.extend(["search_results", "detail_page", "filter_panel"])
    if any(w in q for w in ("job", "career", "hiring", "apply", "vacancy")):
        types.extend(["search_results", "detail_page", "form_page", "filter_panel"])
    if any(w in q for w in ("flight", "hotel", "trip", "travel", "book")):
        types.extend(["search_results", "detail_page", "form_page", "filter_panel", "pagination"])
    if any(w in q for w in ("course", "tutorial", "learn", "video", "youtube")):
        types.extend(["search_results", "detail_page", "article"])
    if any(w in q for w in ("hackathon", "contest", "challenge")):
        types.extend(["search_results", "detail_page", "form_page"])
    if not types:
        types.extend(["search_results", "detail_page"])
    seen = set()
    return [t for t in types if not (t in seen or seen.add(t))]


def _flow_summary(steps: list[dict], max_steps: int = 6) -> dict:
    lines = []
    page_types = []
    for step in steps[:max_steps]:
        page_type = _infer_page_type(step)
        page_types.append(page_type)
        snippet = _step_text(step)[:110]
        if snippet:
            lines.append(f"{page_type}: {snippet}")
    unique_page_types = []
    for page_type in page_types:
        if page_type not in unique_page_types:
            unique_page_types.append(page_type)
    return {
        "page_types": unique_page_types,
        "summary": " -> ".join(unique_page_types) if unique_page_types else "unknown",
        "steps": lines,
    }


def learn_from_run(query: str, steps: list[dict], result: str, success: bool):
    """Store site- and web-level learnings from a completed run."""
    if not steps and not result:
        return

    knowledge = _load()

    _learn_site_performance(knowledge, steps, result, success)
    _learn_query_patterns(knowledge, query, steps, success)
    _learn_web_patterns(knowledge, steps, result, success)
    _learn_site_flows(knowledge, steps, result, success)
    _learn_obstacle_solutions(knowledge, steps, result)

    _save(knowledge)


def _learn_site_performance(knowledge: dict, steps: list[dict], result: str, success: bool):
    if not steps:
        return

    sites_node = knowledge.setdefault("sites", {})
    domain_steps: dict[str, list[dict]] = {}

    for step in steps:
        domain = _normalize_domain(step.get("url", ""))
        if not domain or domain in IGNORED_DOMAINS:
            continue
        domain_steps.setdefault(domain, []).append(step)

    result_lower = (result or "").lower()
    failure_signals = ["blocked", "captcha", "could not", "unable", "failed", "error", "not found", "access denied"]

    for domain, domain_step_list in domain_steps.items():
        site = sites_node.setdefault(domain, _blank_site_entry())
        site["runs"] = site.get("runs", 0) + 1
        site["total_steps"] = site.get("total_steps", 0) + len(domain_step_list)
        site["avg_steps"] = round(site["total_steps"] / site["runs"])
        site["last_seen"] = datetime.now().strftime("%Y-%m-%d")

        domain_in_result = domain in result_lower
        near_failure = False
        if domain_in_result:
            idx = result_lower.find(domain)
            context = result_lower[max(0, idx - 150): idx + 150]
            near_failure = any(sig in context for sig in failure_signals)

        if success and domain_in_result and not near_failure:
            site["success_count"] = site.get("success_count", 0) + 1
        elif near_failure:
            site["fail_count"] = site.get("fail_count", 0) + 1


def _learn_query_patterns(knowledge: dict, query: str, steps: list[dict], success: bool):
    if not success or not steps:
        return

    patterns = knowledge.setdefault("query_patterns", {})

    google_searches = []
    for step in steps:
        url = step.get("url", "")
        if "google.com/search" in url or "google.com/search" in step.get("detail", ""):
            match = re.search(r"[?&]q=([^&]+)", url)
            if match:
                search_q = match.group(1).replace("+", " ").replace("%20", " ")
                google_searches.append(search_q)
        if step.get("action") in ("type", "fill", "input") and step.get("description"):
            desc = step["description"]
            if "search" in desc.lower() and len(desc) > 10:
                google_searches.append(desc[:100])

    if not google_searches:
        return

    category = _call_llm(
        f"""What is the category of this search query in 2-3 words?
Query: "{query}"
Return only 2-3 words, e.g. "flight price search", "product comparison", "job search", "tutorial search".""",
        task_type="planning",
    )

    if category:
        category = category.strip().lower()[:50]
        cat_patterns = patterns.setdefault(category, [])
        for s in google_searches[:2]:
            _append_unique(cat_patterns, s, limit=5)


def _learn_web_patterns(knowledge: dict, steps: list[dict], result: str, success: bool):
    if not steps:
        return

    patterns = knowledge.setdefault("web_patterns", {})
    flow = _flow_summary(steps)
    page_types = flow["page_types"] or ["unknown"]
    result_snippet = (result or "").strip()[:180]

    for step in steps:
        page_type = _infer_page_type(step)
        bucket = patterns.setdefault(page_type, _blank_web_bucket())
        bucket["count"] = bucket.get("count", 0) + 1

        hint = _step_text(step)[:140]
        _append_unique(bucket.setdefault("hints", []), hint, limit=8)

        if page_type in ("search_results", "detail_page", "filter_panel", "form_page", "pagination") and hint:
            _append_unique(
                bucket.setdefault("examples", []),
                {
                    "summary": hint,
                    "domain": _normalize_domain(step.get("url", "")),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                },
                limit=6,
            )

    # Store the flow against the dominant page type sequence.
    dominant = page_types[0]
    bucket = patterns.setdefault(dominant, _blank_web_bucket())
    _append_unique(
        bucket.setdefault("flows", []),
        {
            "summary": flow["summary"],
            "steps": flow["steps"],
            "result": result_snippet,
            "success": success,
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        limit=8,
    )


def _learn_site_flows(knowledge: dict, steps: list[dict], result: str, success: bool):
    if not steps:
        return

    sites_node = knowledge.setdefault("sites", {})
    domain_sequences: dict[str, list[dict]] = {}

    for step in steps:
        domain = _normalize_domain(step.get("url", ""))
        if not domain or domain in IGNORED_DOMAINS:
            continue
        domain_sequences.setdefault(domain, []).append(step)

    for domain, sequence in domain_sequences.items():
        if len(sequence) < 2:
            continue

        site = sites_node.setdefault(domain, _blank_site_entry())
        flow = _flow_summary(sequence)
        page_type = flow["page_types"][0] if flow["page_types"] else "unknown"
        page_flows = site.setdefault("page_flows", {})
        bucket = page_flows.setdefault(page_type, [])

        _append_unique(
            bucket,
            {
                "summary": flow["summary"],
                "steps": flow["steps"],
                "result": (result or "").strip()[:180],
                "success": success,
                "date": datetime.now().strftime("%Y-%m-%d"),
            },
            limit=5,
        )

        if success and not site.get("navigation_hint"):
            # Keep the hint compact and action-oriented.
            site["navigation_hint"] = flow["summary"].replace("_", " ")[:120]


def _learn_obstacle_solutions(knowledge: dict, steps: list[dict], result: str):
    if not result:
        return

    obstacles = knowledge.setdefault("obstacle_solutions", [])
    result_lower = result.lower()
    obstacle_keywords = {
        "captcha": "CAPTCHA detected",
        "login wall": "Login wall encountered",
        "bot detection": "Bot detection triggered",
        "popup": "Popup or modal appeared",
        "slow loading": "Page slow to load",
        "no results": "Search returned no results",
    }

    for keyword, label in obstacle_keywords.items():
        if keyword in result_lower:
            idx = result_lower.find(keyword)
            context_after = result[idx: idx + 300]
            if any(w in result_lower[idx:] for w in ("instead", "navigated", "tried", "found", "switched")):
                entry = {
                    "obstacle": label,
                    "context": context_after[:200],
                    "date": datetime.now().strftime("%Y-%m-%d"),
                }
                if not any(o.get("obstacle") == label and o.get("context", "")[:50] == entry["context"][:50] for o in obstacles[-10:]):
                    obstacles.append(entry)
                    obstacles[:] = obstacles[-20:]


def get_learned_context(query: str) -> str:
    """Return the most relevant learned knowledge for a given query."""
    knowledge = _load()
    q = (query or "").lower()
    relevant_page_types = _infer_query_page_types(q)
    lines = []

    lines.append("## LEARNED WEB PATTERNS")
    for page_type in relevant_page_types[:4]:
        bucket = knowledge.get("web_patterns", {}).get(page_type, {})
        hints = bucket.get("hints", [])[:3]
        flows = bucket.get("flows", [])[:2]
        if not hints and not flows:
            continue
        lines.append(f"- {page_type} (seen {bucket.get('count', 0)} times)")
        for hint in hints:
            lines.append(f"  → {hint}")
        for flow in flows:
            lines.append(f"  ↳ flow: {flow.get('summary', 'unknown')}")

    # Site flows still matter, but only as examples of reusable navigation patterns.
    sites = knowledge.get("sites", {})
    rich_sites = sorted(
        [(domain, site) for domain, site in sites.items() if isinstance(site, dict) and site.get("success_count", 0) > 0],
        key=lambda x: x[1].get("success_count", 0),
        reverse=True,
    )[:4]
    if rich_sites:
        lines.append("\n## LEARNED SITE FLOWS")
        for domain, site in rich_sites:
            hint = site.get("navigation_hint", "")
            if hint:
                lines.append(f"- {domain}: {hint}")
            page_flows = site.get("page_flows", {})
            for page_type in relevant_page_types[:2]:
                flows = page_flows.get(page_type, [])
                if flows:
                    lines.append(f"  • {page_type}: {flows[0].get('summary', 'unknown')}")

    obstacles = knowledge.get("obstacle_solutions", [])[-4:]
    if obstacles:
        lines.append("\n## RECENT OBSTACLES")
        for item in obstacles:
            lines.append(f"- {item.get('obstacle', 'Obstacle')}: {item.get('context', '')[:120]}")

    patterns = knowledge.get("query_patterns", {})
    if patterns:
        lines.append("\n## EFFECTIVE SEARCH PATTERNS")
        for category, items in list(patterns.items())[:3]:
            if items:
                lines.append(f"- {category}")
                for item in items[:2]:
                    lines.append(f"  → {item}")

    return "\n".join(lines) if lines else ""
