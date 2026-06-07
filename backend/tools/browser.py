import asyncio
from browser_use import Agent, Browser, BrowserProfile
from browser_use.llm.google.chat import ChatGoogle
from backend.config import settings

_browser: Browser | None = None
_browser_lock = asyncio.Lock()

# Step log store: task_id -> list of step dicts
_step_logs: dict[str, list[dict]] = {}


def get_llm():
    from backend.tools.model_selector import get_model_for_tier, ModelTier
    return ChatGoogle(
        model=get_model_for_tier(ModelTier.LARGE),
        api_key=settings.google_api_key,
        temperature=0,
    )


def _make_browser(keep_alive: bool = True) -> Browser:
    headless = os.environ.get("HEADLESS", "false").lower() == "true"
    return Browser(
        browser_profile=BrowserProfile(
            headless=headless,
            disable_security=True,
            keep_alive=keep_alive,
            minimum_wait_page_load_time=0.5,
            wait_between_actions=0.3,
            # Disable default extensions (uBlock, cookie banners) — saves 3-8s startup
            enable_default_extensions=False,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        )
    )


async def get_browser() -> Browser:
    global _browser
    async with _browser_lock:
        if _browser is None:
            _browser = _make_browser(keep_alive=True)
    return _browser


def _make_agent(task: str, browser: Browser, task_type: str = "",
                task_id: str = "", temporal: bool = False,
                learned_ctx: str = "") -> Agent:
    from backend.tools.context import get_system_context

    def on_step(browser_state, agent_output, step_number):
        """Capture each step for real-time UI streaming + self-verification."""
        try:
            url = getattr(browser_state, "url", "") or ""
            title = getattr(browser_state, "title", "") or ""

            action_name = ""
            action_detail = ""
            if agent_output and hasattr(agent_output, "action"):
                actions = agent_output.action or []
                if actions:
                    first = actions[0]
                    action_name = type(first).__name__.lower().replace("action", "")
                    for attr in ("url", "query", "text", "selector", "value"):
                        val = getattr(first, attr, None)
                        if val:
                            action_detail = str(val)[:80]
                            break

            description = ""
            if agent_output:
                for attr in ("next_goal", "thinking", "memory"):
                    val = getattr(agent_output, attr, None)
                    if val:
                        description = str(val)[:120]
                        break

            step = {
                "step": step_number,
                "url": url,
                "title": title,
                "action": action_name,
                "detail": action_detail,
                "description": description,
            }

            if task_id:
                _step_logs.setdefault(task_id, [])
                _step_logs[task_id].append(step)

        except Exception:
            pass

    # Fallback LLM — always gemini-3.1-flash-lite (highest rate limit)
    from browser_use.llm.google.chat import ChatGoogle as _ChatGoogle
    fallback_llm = _ChatGoogle(
        model="gemini-3.1-flash-lite",
        api_key=settings.google_api_key,
        temperature=0,
    )

    return Agent(
        task=task,
        llm=get_llm(),
        fallback_llm=fallback_llm,
        browser=browser,

        # ── Timeouts ──
        llm_timeout=60,
        step_timeout=120,

        # ── Principle 2: Smarter Planning ──
        enable_planning=True,          # Agent writes plan before acting
        planning_replan_on_stall=3,    # Replan after 3 steps without progress

        # ── Principle 5: Recovery Loop ──
        loop_detection_enabled=True,
        loop_detection_window=8,       # Tighter than default 20 — catch loops faster
        max_failures=4,                # Stop after 4 consecutive failures
        final_response_after_failure=True,  # Always return something, never empty

        # ── Principle 6: Self-Verification ──
        use_judge=True,                # LLM judges if task was actually completed

        # ── Principle 1 + 7: Better Observation + CoT ──
        use_vision=True,               # Screenshot + DOM together
        use_thinking=True,             # Chain-of-thought before every action

        # Don't append internal todo.md/results.md to the final answer
        display_files_in_done_text=False,

        # ── System context: all 7 principles + learned memory + site knowledge ──
        extend_system_message=get_system_context(task_type, temporal=temporal, task=task)
            + ("\n\n" + learned_ctx if learned_ctx else ""),

        # ── Step streaming ──
        register_new_step_callback=on_step,
    )


def get_steps(task_id: str) -> list[dict]:
    return _step_logs.get(task_id, [])


def clear_steps(task_id: str):
    _step_logs.pop(task_id, None)


def _strip_attachments(text: str) -> str:
    """
    Remove internal agent scaffolding from final output:
    - todo.md / results.md file contents
    - 'Attachments:' section
    - Action log lines (🔗 Navigated, Typed, Clicked, etc.)
    """
    if not text:
        return text

    # Cut everything from "Attachments:" onwards
    for marker in ["Attachments:", "\nAttachments\n", "---\ntodo.md", "---\nresults.md"]:
        if marker in text:
            text = text[:text.index(marker)].strip()

    # Remove individual action log lines
    ACTION_PREFIXES = (
        "🔗", "Typed ", "Clicked ", "Scrolled", "Navigated",
        "Successfully replaced", "💡", "Opened new tab",
        "[ ]", "[x]", "# Parking", "# Travel", "# Research",
        "Tasks:", "## Tasks",
    )
    lines = text.split('\n')
    clean_lines = [l for l in lines if not any(l.strip().startswith(p) for p in ACTION_PREFIXES)]
    return "\n".join(clean_lines).strip()


def _extract_best_result(agent_history) -> str:
    """Fallback chain: final_result → filtered extracted_content → action_results."""
    ACTION_PREFIXES = (
        "🔗", "Typed ", "Clicked ", "Scrolled", "Navigated",
        "Successfully replaced", "💡", "✅", "❌", "📄",
        "[ ]", "[x]", "Opened new tab",
    )

    def is_action_log(text: str) -> bool:
        t = text.strip()
        return any(t.startswith(p) for p in ACTION_PREFIXES) or len(t) < 60

    # 1. Try official final result — strip attachments first
    final = _strip_attachments(agent_history.final_result() or "")
    if final and len(final.strip()) > 80 and not is_action_log(final):
        return final

    # 2. Try extracted_content — filter action logs and attachments
    try:
        extracted = _strip_attachments(agent_history.extracted_content() or "")
        if extracted:
            lines = [l for l in extracted.split('\n') if l.strip() and not is_action_log(l)]
            clean = "\n".join(lines).strip()
            if len(clean) > 80:
                return clean
    except Exception:
        pass

    # 3. Try action_results
    try:
        collected = []
        for r in agent_history.action_results():
            content = _strip_attachments(str(getattr(r, "extracted_content", "") or "").strip())
            if content and len(content) > 80 and not is_action_log(content):
                collected.append(content)
        if collected:
            return "\n\n".join(collected)
    except Exception:
        pass

    return ""


async def run_browser_task(task: str, task_type: str = "", task_id: str = "",
                           temporal: bool = False, max_steps: int = 25) -> str:
    from backend.tools.learner import get_learned_context, learn_from_run
    learned_ctx = get_learned_context(task)
    browser = await get_browser()
    agent = _make_agent(task, browser, task_type, task_id, temporal, learned_ctx)
    history = await agent.run(max_steps=max_steps)
    result = _extract_best_result(history)
    steps = _step_logs.get(task_id, [])
    learn_from_run(task, steps, result, success=bool(result and len(result) > 80))
    return result


async def run_deep_task(task: str, task_type: str = "", task_id: str = "",
                        temporal: bool = False, max_steps: int = 35) -> str:
    global _browser
    from backend.tools.learner import get_learned_context, learn_from_run

    learned_ctx = get_learned_context(task)

    # Always create a fresh browser for each task.
    # The warm browser's internal session gets reset after each run,
    # which leaves it in a state that breaks the next agent.
    # Pre-warm at startup handles cold-start for the first query;
    # subsequent tasks get a clean browser quickly since the OS has Chromium cached.
    browser = _make_browser(keep_alive=False)
    try:
        agent = _make_agent(task, browser, task_type, task_id, temporal, learned_ctx)
        history = await agent.run(max_steps=max_steps)
        result = _extract_best_result(history)
    finally:
        try:
            await browser.close()
        except Exception:
            pass
        # Refresh the warm browser for the next task
        async with _browser_lock:
            if _browser:
                try:
                    await _browser.close()
                except Exception:
                    pass
            _browser = _make_browser(keep_alive=True)

    steps = _step_logs.get(task_id, [])
    learn_from_run(task, steps, result, success=bool(result and len(result) > 80))
    return result


async def run_parallel_tasks(tasks: list[str], task_type: str = "",
                             task_id: str = "", max_steps: int = 25) -> list[str]:
    browser = await get_browser()
    results = []
    for task in tasks:
        try:
            agent = _make_agent(task, browser, task_type, task_id)
            result = await agent.run(max_steps=max_steps)
            results.append(_extract_best_result(result))
        except Exception as e:
            results.append(f"Error: {e}")
    return results


async def close_browser():
    global _browser
    if _browser:
        await _browser.close()
        _browser = None
