"""
Verification — Gap #9
Checks if the agent result actually answers the query, scores confidence,
and flags anything needing human review.
"""

import json
import re
from backend.tools.planner import _call_llm
# Uses SMALL model — verification is structured evaluation, not open-ended reasoning
from backend.memory.agent_memory import BLOCKED_PATTERNS


def verify(query: str, result: str, success_condition: str) -> dict:
    """
    Evaluate the result quality.
    Returns:
        passed: bool
        confidence: int (0-100)
        gaps: list[str]
        needs_human_review: bool
        retry_hint: str
    """
    if not result or len(result.strip()) < 15:
        return {
            "passed": False,
            "confidence": 0,
            "gaps": ["Result is empty or too short"],
            "needs_human_review": True,
            "retry_hint": "Try a different search approach or different website",
        }

    result_lower = result.lower()

    # Quick fail: result contains block indicators
    block_signals = [p for p in BLOCKED_PATTERNS if p in result_lower]
    failure_signals = ["could not find", "unable to", "no results", "blocked", "not available",
                       "failed to", "error occurred", "access denied", "try again"]
    failures = [s for s in failure_signals if s in result_lower]

    if len(failures) >= 3 or len(block_signals) >= 2:
        return {
            "passed": False,
            "confidence": 15,
            "gaps": ["Multiple failure signals detected in result"],
            "needs_human_review": True,
            "retry_hint": "Sites may be blocking access — try Google search approach instead of direct navigation",
        }

    prompt = f"""You are a quality evaluator for a web research agent.

ORIGINAL QUERY: {query}

SUCCESS CONDITION: {success_condition}

AGENT RESULT:
{result[:2000]}

Evaluate strictly and return JSON:
{{
  "passed": true/false,
  "confidence": 0-100,
  "gaps": ["missing item 1", "missing item 2"],
  "needs_human_review": true/false,
  "retry_hint": "specific suggestion to fix the main gap"
}}

Rules:
- passed=true only if the result meaningfully answers the query with concrete data (prices, URLs, names, dates)
- confidence: 90+ = complete answer with sources; 70-89 = good but minor gaps; 50-69 = partial; <50 = poor
- needs_human_review=true if confidence < 50 or result contains hedging language
- retry_hint: one specific actionable suggestion (e.g. "Search Amazon.in directly for current pricing")
- gaps: list only truly missing items, not stylistic preferences

Return only valid JSON, no markdown."""

    raw = _call_llm(prompt, task_type="verification")
    if not raw:
        # Heuristic fallback: check for URLs and concrete data
        has_urls = bool(re.search(r'https?://', result))
        has_prices = bool(re.search(r'₹\d|Rs\.\d|\$\d', result))
        confidence = 60 if (has_urls and has_prices) else 40
        return {
            "passed": confidence >= 50,
            "confidence": confidence,
            "gaps": [],
            "needs_human_review": confidence < 50,
            "retry_hint": "Retry with more specific search terms",
        }

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        v = json.loads(raw.strip())
        v.setdefault("passed", False)
        v.setdefault("confidence", 50)
        v.setdefault("gaps", [])
        v.setdefault("needs_human_review", False)
        v.setdefault("retry_hint", "Try a different search approach")
        return v
    except Exception:
        return {
            "passed": True,
            "confidence": 55,
            "gaps": [],
            "needs_human_review": False,
            "retry_hint": "",
        }
