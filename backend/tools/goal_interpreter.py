"""
Goal Understanding — Gap #1
Detects ambiguity, generates one clarifying question, and defines the success condition.
"""

import json
from datetime import datetime, timedelta
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
    CURRENT_DATE = now.strftime("%A, %B %d, %Y")  # e.g. "Wednesday, July 15, 2026"

    # Resolve common relative dates to concrete calendar dates — LLMs are unreliable
    # at date arithmetic, so compute them here and hand them to the model.
    wd = now.weekday()  # Mon=0 .. Sun=6
    _sat = now - timedelta(days=wd - 5) if wd >= 5 else now + timedelta(days=5 - wd)
    _sun = _sat + timedelta(days=1)
    _tom = now + timedelta(days=1)
    _nsat, _nsun = _sat + timedelta(days=7), _sun + timedelta(days=7)
    _f = lambda d: d.strftime("%A %B %d, %Y")
    DATE_REFERENCE = (
        f"- Today: {_f(now)}\n"
        f"- Tomorrow: {_f(_tom)}\n"
        f'- "this weekend": {_sat.strftime("%B %d")} to {_sun.strftime("%B %d, %Y")}\n'
        f'- "next weekend": {_nsat.strftime("%B %d")} to {_nsun.strftime("%B %d, %Y")}'
    )

    prompt = f"""You are a query analyst for a browser agent. Today's date is {CURRENT_DATE}.

DATE REFERENCE (use these exact dates to resolve relative time phrases):
{DATE_REFERENCE}

Analyse this user query and return JSON with exactly these fields:

QUERY: "{query}"

Rules:
- is_ambiguous: true ONLY if the query is missing critical information (e.g. "find flights" with no cities). Vague words, conditional logic ("if X then Y else Z"), and pronouns referencing prior context are NOT ambiguous.
- NEVER mark as ambiguous: conditional prompts like "If the video has more than 50k views, do X, otherwise do Y" — these are clear instructions. The agent evaluates and executes the correct branch.
- NEVER mark as ambiguous: follow-up pronouns like "it", "them", "the same", "the video" — they reference prior context.
- NEVER mark as ambiguous when "the video" or "it" refers to something mentioned in a prior message, even if the result was "not found" — the agent handles that via the if/else branch.
- clarifying_question: if is_ambiguous=true, write ONE short question. If false, set null.
- success_condition: what a complete correct answer must contain.
- refined_query: rewrite the query to be more precise. IMPORTANT:
  * RELATIVE DATES: if the query says "this weekend", "tomorrow", "tonight", "next weekend", "next Friday", "today" etc., REPLACE that phrase in refined_query with the explicit calendar date(s) from the DATE REFERENCE above (e.g. "this weekend" → "{_sat.strftime("%d")}-{_sun.strftime("%d %B %Y")}"). Critical for flights, hotels and events.
  * If the query contains "latest", "new", "recent", "upcoming", "newest" → add "{CURRENT_YEAR}" to the refined query so searches are time-filtered. Example: "latest trailer of X" → "X {CURRENT_YEAR} latest trailer"
  * If the query mentions a movie/show/album trailer → add "official trailer {CURRENT_YEAR}" and specify the platform (YouTube)
  * Fix typos and hyphenation (e.g. "ice cream-man" → "Ice Cream Man")
- temporal_intent: true if the query uses words like latest/new/recent/upcoming/current/this year, OR a relative date (this weekend, tomorrow, next week, etc.); false otherwise

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
