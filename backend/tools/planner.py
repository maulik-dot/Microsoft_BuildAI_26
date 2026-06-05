"""
Task planner — uses small model for planning (cheap + fast), large model not needed here.
"""

from google import genai


def _call_llm(prompt: str, task_type: str = "planning") -> str:
    """Call LLM at the correct tier for this task type."""
    from backend.config import settings
    from backend.tools.model_selector import get_model

    model = get_model(task_type)
    try:
        client = genai.Client(api_key=settings.google_api_key)
        r = client.models.generate_content(model=model, contents=prompt)
        return r.text.strip()
    except Exception:
        return ""


def plan_research(query: str) -> str:
    """Generate a web research strategy. Uses SMALL model — planning is structured."""
    result = _call_llm(f"""You are a research strategist. For this query, write a concise step-by-step web research plan.

QUERY: {query}

Write a numbered plan (max 8 steps) covering:
1. Best Google search queries to use (give exact query strings)
2. Which websites/sources to visit (be specific: site names, URLs)
3. What to look for on each page
4. How to cross-reference or verify the information
5. What the final structured answer should contain

Be specific — give exact search terms, exact site names. No generic advice.
Return ONLY the numbered plan.""", task_type="planning")

    return f"## RESEARCH PLAN\n{result}\n\n## BEGIN RESEARCH\n" if result else ""


def plan_task(goal: str, task_type: str) -> str:
    """Generate a site-specific execution plan. Uses SMALL model."""
    result = _call_llm(f"""You are a browser task planner. Convert this goal into a specific step-by-step browser plan.

GOAL: {goal}
TASK TYPE: {task_type}

Write a concise numbered plan (max 8 steps):
1. Best URL to start
2. Exact search terms to type
3. Filters/buttons to click
4. What data to extract at each step
5. How to handle common obstacles (popups, login walls)

Be specific. Use real site names. Return ONLY the numbered plan.""", task_type="planning")

    return f"## EXECUTION PLAN\n{result}\n\n## TASK\n" if result else ""


def replan(original_goal: str, step_tracker_dump: str, retry_hint: str) -> str:
    """Revised plan after failure. Uses SMALL model — structured reformulation."""
    result = _call_llm(f"""A web research agent tried to complete this goal but failed.

ORIGINAL GOAL: {original_goal}

PREVIOUS ATTEMPT STATUS:
{step_tracker_dump}

VERIFIER SUGGESTION: {retry_hint}

Write a NEW concise plan (max 6 steps) that:
1. Avoids the approaches that already failed
2. Applies the verifier's suggestion
3. Uses alternative sites or search strategies

Return ONLY the numbered plan.""", task_type="replan")

    return f"## REVISED PLAN (retry)\n{result}\n\n## TASK\n" if result else ""
