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
    """
    Generate a web research strategy with engineered search queries.
    Combines LLM planning with precision Google operator injection.
    """
    from backend.tools.query_engineer import engineer_search_plan

    # Build engineered queries (operators, multi-angle, hypothetical)
    search_plan = engineer_search_plan(query)

    # LLM adds the step-by-step execution logic on top
    result = _call_llm(f"""You are a research strategist. A search engineer has already prepared precision queries for this research task. Your job is to write the EXECUTION steps.

QUERY: {query}

PREPARED SEARCHES (use these exact queries in order):
{search_plan}

Write a numbered execution plan (max 6 steps) covering:
1. Which prepared query to use first and why
2. What to look for and extract from each page
3. How to cross-reference results across sources
4. What the final structured answer must contain

Be specific. Reference the exact queries above. Return ONLY the numbered plan.""", task_type="planning")

    return f"{search_plan}\n## EXECUTION PLAN\n{result}\n\n## BEGIN RESEARCH\n" if result else search_plan


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
