"""
Goal Understanding — Gap #1
Detects ambiguity, generates one clarifying question, and defines the success condition.
"""

import json
from datetime import datetime
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
    now = datetime.now()
    CURRENT_YEAR = str(now.year)
    CURRENT_DATE = now.strftime("%B %d, %Y")  # e.g. "June 05, 2026"

    prompt = f"""You are a query analyst for a web research agent. Today's date is {CURRENT_DATE}.

Analyse this user query and return JSON with exactly these fields:

QUERY: "{query}"

Rules:
- is_ambiguous: true ONLY if the query is missing critical information (e.g. "find flights" with no cities). Vague words, conditional logic ("if X then Y else Z"), and pronouns referencing prior context are NOT ambiguous.
- NEVER mark as ambiguous: conditional prompts like "If the video has more than 50k views, do X, otherwise do Y" — these are clear instructions, not ambiguous.
- NEVER mark as ambiguous: follow-up pronouns like "it", "them", "the same" — they reference prior context.
- clarifying_question: if is_ambiguous=true, write ONE short question. If false, set null.
- success_condition: what a complete correct answer must contain.
- refined_query: rewrite the query to be more precise. IMPORTANT:
  * If the query contains "latest", "new", "recent", "upcoming", "newest" → add "{CURRENT_YEAR}" to the refined query so searches are time-filtered. Example: "latest trailer of X" → "X {CURRENT_YEAR} latest trailer"
  * If the query mentions a movie/show/album trailer → add "official trailer {CURRENT_YEAR}" and specify the platform (YouTube)
  * Fix typos and hyphenation (e.g. "ice cream-man" → "Ice Cream Man")
- temporal_intent: true if the query uses words like latest/new/recent/upcoming/current/this year, false otherwise

Return only valid JSON, no markdown:
{{
  "is_ambiguous": false,
  "clarifying_question": null,
  "success_condition": "...",
  "refined_query": "...",
  "temporal_intent": false
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
        result.setdefault("temporal_intent", False)
        return result
    except Exception:
        return {
            "is_ambiguous": False,
            "clarifying_question": None,
            "success_condition": "The query is fully answered with relevant information.",
            "refined_query": query,
        }
