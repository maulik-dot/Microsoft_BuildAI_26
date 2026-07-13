"""
Task planner — uses small model for planning (cheap + fast), large model not needed here.
"""

import asyncio
from google import genai


def _call_llm(prompt: str, task_type: str = "planning") -> str:
    """
    Call the LLM at the correct tier for this task type. No pre-flight probe:
    try the resolved/primary model first and fall back down the tier list only if a
    real call fails, cooling down exhausted (429) / unavailable (404) models so we
    don't keep hitting them.
    """
    from backend.tools.model_selector import candidates, note_error
    from backend.tools.llm_client import complete_text

    last_err = None
    for model in candidates(task_type):
        try:
            # Provider-aware: Gemini names hit the Google SDK, "provider/model"
            # names hit OpenRouter. Fallback rotates down the tier list on failure.
            text = complete_text(model, prompt)
            if text:
                return text
        except Exception as e:
            last_err = e
            note_error(model, e)
            continue

    print(f"[LLM ERROR] all {task_type} candidates failed: {last_err}")
    return ""


async def _call_llm_async(prompt: str, task_type: str = "planning") -> str:
    """Async wrapper around the blocking _call_llm so planning calls can overlap."""
    return await asyncio.to_thread(_call_llm, prompt, task_type)


def _exec_plan_prompt(query: str, search_plan: str) -> str:
    return f"""You are a browser strategist. A search engineer has already prepared precision queries for this browsing task. Your job is to write the EXECUTION steps.

QUERY: {query}

PREPARED SEARCHES (use these exact queries in order):
{search_plan}

Write a numbered execution plan (max 6 steps) covering:
1. Which prepared query to use first and why
2. What to look for and extract from each page
3. How to cross-reference results across sources
4. What the final structured answer must contain

Be specific. Reference the exact queries above. Return ONLY the numbered plan."""


def plan_research(query: str) -> str:
    """
    Generate a browser strategy with engineered search queries.
    Combines LLM planning with precision Google operator injection.
    """
    from backend.tools.query_engineer import engineer_search_plan

    # Build engineered queries (operators, multi-angle, hypothetical)
    search_plan = engineer_search_plan(query)

    # LLM adds the step-by-step execution logic on top
    result = _call_llm(_exec_plan_prompt(query, search_plan), task_type="planning")

    return f"{search_plan}\n## EXECUTION PLAN\n{result}\n\n## BEGIN RESEARCH\n" if result else search_plan


async def plan_research_async(query: str) -> str:
    """
    Async plan builder that runs the two independent LLM workloads concurrently:
      • the HyDE hypothetical (a 2-call chain), and
      • the execution-plan call (built on the regex-only search plan).
    The regex parts (operator queries, angles, sources) are instant, so the critical
    path drops from ~3 serial LLM calls to ~2.
    """
    from backend.tools.query_engineer import engineer_search_plan, generate_hypothetical_async

    # Regex-only search plan (no HyDE yet) — enough context for the exec-plan call.
    base_plan = engineer_search_plan(query, hypothetical="")

    hypothetical, exec_result = await asyncio.gather(
        generate_hypothetical_async(query),
        _call_llm_async(_exec_plan_prompt(query, base_plan), task_type="planning"),
    )

    # Reassemble the full plan now that the hypothetical is available.
    full_plan = engineer_search_plan(query, hypothetical=hypothetical)
    return f"{full_plan}\n## EXECUTION PLAN\n{exec_result}\n\n## BEGIN RESEARCH\n" if exec_result else full_plan


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
    result = _call_llm(f"""A browser agent tried to complete this goal but failed.

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
