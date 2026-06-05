"""
Goal Understanding — Gap #1
Detects ambiguity, generates one clarifying question, and defines the success condition.
"""

import json
from backend.tools.planner import _call_llm
# Uses SMALL model — ambiguity detection is a simple classification task


def interpret(query: str) -> dict:
    """
    Analyse the query before any browsing starts.
    Returns:
        is_ambiguous: bool
        clarifying_question: str | None  — exactly one question if ambiguous
        success_condition: str           — what "done" looks like
        refined_query: str               — cleaned-up version of the query
    """
    prompt = f"""You are a query analyst for a web research agent.

Analyse this user query and return JSON with exactly these fields:

QUERY: "{query}"

Rules:
- is_ambiguous: true ONLY if the query is missing information that would change WHERE to search or WHAT to search for (e.g. "find flights" with no cities, "find a job" with no role). Vague style ("best", "good", "cheap") is NOT ambiguous.
- clarifying_question: if is_ambiguous=true, write ONE short question to fill the most critical gap. If false, set null.
- success_condition: a single sentence describing what a complete, correct answer must contain (e.g. "A list of at least 3 flights with prices, times and booking URLs").
- refined_query: the query rewritten to be more precise and actionable, fixing obvious typos or vagueness. If already good, return as-is.

Return only valid JSON, no markdown:
{{
  "is_ambiguous": false,
  "clarifying_question": null,
  "success_condition": "...",
  "refined_query": "..."
}}"""

    raw = _call_llm(prompt, task_type="ambiguity_check")
    if not raw:
        return {
            "is_ambiguous": False,
            "clarifying_question": None,
            "success_condition": "The query is fully answered with relevant, accurate information.",
            "refined_query": query,
        }

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        result = json.loads(raw.strip())
        result.setdefault("is_ambiguous", False)
        result.setdefault("clarifying_question", None)
        result.setdefault("success_condition", "The query is fully answered.")
        result.setdefault("refined_query", query)
        return result
    except Exception:
        return {
            "is_ambiguous": False,
            "clarifying_question": None,
            "success_condition": "The query is fully answered with relevant information.",
            "refined_query": query,
        }
