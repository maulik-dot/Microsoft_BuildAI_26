"""
Task planner — uses Gemini to generate a research strategy for any query.
"""

import json
import os
from google import genai


def _call_llm(prompt: str) -> str:
    from backend.config import settings

    # Try OpenAI first
    if settings.openai_api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key)
            r = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return r.choices[0].message.content.strip()
        except Exception:
            pass

    # Fall back to Gemini
    try:
        from backend.tools.model_selector import get_working_model
        client = genai.Client(api_key=settings.google_api_key)
        r = client.models.generate_content(model=get_working_model(), contents=prompt)
        return r.text.strip()
    except Exception:
        return ""


def plan_research(query: str) -> str:
    """Generate a web research strategy for any natural language query."""
    result = _call_llm(f"""You are a research strategist. For this query, write a concise step-by-step web research plan.

QUERY: {query}

Write a numbered plan (max 8 steps) covering:
1. Best Google search queries to use (give exact query strings)
2. Which websites/sources to visit (be specific: site names, URLs)
3. What to look for on each page
4. How to cross-reference or verify the information
5. What the final structured answer should contain

Be specific — give exact search terms, exact site names. No generic advice.
Return ONLY the numbered plan.""")

    return f"## RESEARCH PLAN\n{result}\n\n## BEGIN RESEARCH\n" if result else ""


def plan_task(goal: str, task_type: str) -> str:
    """Generate a site-specific execution plan for a specialized task."""
    result = _call_llm(f"""You are a browser task planner. Convert this goal into a specific step-by-step browser plan.

GOAL: {goal}
TASK TYPE: {task_type}

Write a concise numbered plan (max 8 steps):
1. Best URL to start
2. Exact search terms to type
3. Filters/buttons to click
4. What data to extract at each step
5. How to handle common obstacles (popups, login walls)

Be specific. Use real site names. Return ONLY the numbered plan.""")

    return f"## EXECUTION PLAN\n{result}\n\n## TASK\n" if result else ""
