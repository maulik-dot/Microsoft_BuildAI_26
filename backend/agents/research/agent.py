"""
General-purpose web research agent — fully capable version.
Handles all 10 core capabilities:
1. Goal Understanding     — ambiguity detection + clarifying questions
2. Browser Perception     — via browser-use + augmented system context
3. Navigation             — via browser-use + wrong-page detection in context
4. Interaction            — via browser-use + form/modal handling in context
5. Planning & Decomposition — step tracker + dynamic re-planning on failure
6. Memory & State         — persistent memory + in-task scratchpad
7. Cross-Service          — scratchpad passes data between site sub-tasks
8. Recovery & Resilience  — retry loop (max 2) with revised plan + CAPTCHA guidance
9. Verification           — verifier scores result, flags gaps, triggers retry
10. Reporting Back        — confidence score, needs_review flag, gap list
"""

import time
from backend.tools.browser import run_deep_task
from backend.tools.planner import plan_research, replan
from backend.tools.step_tracker import StepTracker, TaskScratchpad, parse_plan_steps
from backend.tools.goal_interpreter import interpret
from backend.tools.verifier import verify
from backend.memory.agent_memory import get_general_context, update_general
from backend.tools.model_selector import record_eval, get_model_for_tier, ModelTier

MAX_RETRIES = 2


async def run_research(query: str, task_id: str = "") -> dict:
    """
    Full research pipeline with all 10 capabilities wired in.
    Returns a dict with: query, result, confidence, needs_review, gaps,
    and optionally: status="waiting_user", clarifying_question.
    """

    # ── 1. GOAL UNDERSTANDING ──────────────────────────────────────────────
    goal = interpret(query)

    if goal["is_ambiguous"]:
        return {
            "status": "waiting_user",
            "clarifying_question": goal["clarifying_question"],
            "query": query,
            "result": None,
            "confidence": 0,
            "needs_review": False,
            "gaps": ["Query is ambiguous — waiting for user clarification"],
        }

    refined_query = goal["refined_query"]
    success_condition = goal["success_condition"]

    # ── 2. PLANNING & STATE ────────────────────────────────────────────────
    memory_ctx = get_general_context(refined_query)
    plan_text = plan_research(refined_query)
    steps = parse_plan_steps(plan_text)
    tracker = StepTracker(steps)
    scratchpad = TaskScratchpad()

    result = ""
    verdict = {}

    for attempt in range(MAX_RETRIES + 1):
        # ── 3. BUILD TASK WITH FULL CONTEXT ───────────────────────────────
        if attempt == 0:
            current_plan = plan_text
        else:
            current_plan = replan(refined_query, tracker.to_prompt_block(), verdict.get("retry_hint", ""))

        task = _build_task(refined_query, memory_ctx, current_plan, scratchpad, success_condition)

        # Fewer steps on retries — more focused
        max_steps = 40 if attempt == 0 else 20

        # ── 4. BROWSER EXECUTION ──────────────────────────────────────────
        browser_model = get_model_for_tier(ModelTier.LARGE)
        t_start = time.time()
        result = await run_deep_task(task, task_type="research", max_steps=max_steps)
        latency_ms = int((time.time() - t_start) * 1000)

        # ── 5. VERIFICATION ───────────────────────────────────────────────
        verdict = verify(refined_query, result, success_condition)

        # ── 5a. RECORD EVAL ───────────────────────────────────────────────
        record_eval(
            task_type="browser_agent",
            model=browser_model,
            passed=verdict.get("passed", False),
            confidence=verdict.get("confidence", 0),
            latency_ms=latency_ms,
        )

        # Extract key data points into scratchpad for potential retry
        _update_scratchpad(scratchpad, result, attempt)

        if verdict["passed"]:
            break

        # Mark failed steps and continue to retry
        for i, step in enumerate(tracker.get_pending()):
            tracker.mark_failed(i, verdict.get("retry_hint", "verification failed"))

    # ── 6. MEMORY UPDATE ──────────────────────────────────────────────────
    update_general(refined_query, result, success=verdict.get("passed", False))

    # ── 7. REPORTING ──────────────────────────────────────────────────────
    return {
        "query": refined_query,
        "result": result,
        "confidence": verdict.get("confidence", 50),
        "needs_review": verdict.get("needs_human_review", False),
        "gaps": verdict.get("gaps", []),
        "status": "completed",
    }


def _build_task(query: str, memory_ctx: str, plan: str, scratchpad: TaskScratchpad, success_condition: str) -> str:
    parts = [memory_ctx, plan]

    if not scratchpad.is_empty():
        parts.append(scratchpad.dump())

    parts.append(f"""RESEARCH QUERY: {query}

SUCCESS CONDITION: {success_condition}

RESEARCH INSTRUCTIONS:
1. Start at https://www.google.com — search for the most relevant query
2. Open the top 3-5 most relevant results
3. Extract thorough, accurate information from each page
4. Cross-reference across sources for accuracy
5. If one approach fails, try a different site or search query
6. After visiting each site, note key findings in your memory

HANDLING OBSTACLES:
- Cookie banners: click Accept immediately
- Login walls: close popup, continue browsing
- Paywalls: go back to Google, find a different source
- Slow pages: wait 3 seconds and scroll
- CAPTCHA: navigate away and try a different source

OUTPUT FORMAT:
- Direct answer to the query upfront (1-2 sentences)
- Detailed findings in sections with tables/lists where appropriate
- Source URLs for every major claim
- "Key Takeaway" at the end""")

    return "\n\n".join(parts)


def _update_scratchpad(scratchpad: TaskScratchpad, result: str, attempt: int):
    """Extract key values from result into scratchpad for cross-service use."""
    import re

    prices = re.findall(r'₹[\d,]+', result)
    if prices:
        scratchpad.set(f"prices_found_attempt_{attempt}", ", ".join(prices[:3]))

    urls = re.findall(r'https?://[^\s\)]+', result)
    if urls:
        scratchpad.set(f"urls_found_attempt_{attempt}", ", ".join(urls[:3]))
