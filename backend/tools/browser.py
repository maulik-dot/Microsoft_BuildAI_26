import asyncio
import os
from browser_use import Agent, Browser, BrowserProfile
from browser_use.llm.google.chat import ChatGoogle
from backend.config import settings

_browser: Browser | None = None
_browser_lock = asyncio.Lock()
# Exclusive-use lock: only one agent may drive the shared warm browser at a time.
# A second, concurrent task falls back to its own isolated fresh browser.
_warm_in_use = asyncio.Lock()

# Step log store: task_id -> list of step dicts
_step_logs: dict[str, list[dict]] = {}


def get_llm():
    from backend.tools.model_selector import get_model_for_tier, ModelTier
    from backend.tools.llm_client import make_browser_llm
    # LARGE tier — resolves to a Gemini model normally, or an OpenRouter model
    # (openai/gpt-4o, google/gemini-2.5-flash) once the direct key is exhausted.
    return make_browser_llm(get_model_for_tier(ModelTier.LARGE))


def _make_browser(keep_alive: bool = True) -> Browser:
    headless = os.environ.get("HEADLESS", "false").lower() == "true"
    return Browser(
        browser_profile=BrowserProfile(
            headless=headless,
            disable_security=True,
            # Container-safe: run Chromium without the sandbox (required as root in a
            # container, e.g. Hugging Face Spaces) and avoid /dev/shm crashes.
            chromium_sandbox=False,
            args=["--disable-dev-shm-usage"],
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

    # Fallback LLM — the resolved SMALL model (validated at startup, highest rate
    # limit). Provider-aware: falls through to OpenRouter (openai/gpt-4o-mini,
    # google/gemini-2.5-flash-lite) if the direct-key Gemini models are cooling down.
    from backend.tools.model_selector import get_model_for_tier as _get_tier, ModelTier as _Tier
    from backend.tools.llm_client import make_browser_llm as _make_llm
    fallback_llm = _make_llm(_get_tier(_Tier.SMALL))

    return Agent(
        task=task,
        llm=get_llm(),
        fallback_llm=fallback_llm,
        browser=browser,

        # ── Timeouts ── (flash models answer in seconds; high ceilings just delay
        # failover to fallback_llm on a hang)
        llm_timeout=30,
        step_timeout=90,

        # ── Planning ── We inject our own detailed plan via plan_research(), so
        # browser-use's internal planner is redundant. Disabling it removes the plan
        # fields from every step's output schema (fewer tokens generated per step).
        enable_planning=False,

        # ── Principle 5: Recovery Loop ──
        loop_detection_enabled=True,
        loop_detection_window=8,       # Tighter than default 20 — catch loops faster
        max_failures=4,                # Stop after 4 consecutive failures
        final_response_after_failure=True,  # Always return something, never empty

        # ── Verification ── The pipeline's verify() does the real result-quality
        # gating + retry. browser-use's use_judge is a telemetry-only LLM call at the
        # end of each run (it does NOT override the result), so it's pure overhead.
        use_judge=False,

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
        # Only filter pure action log lines, not short but valid answers
        return any(t.startswith(p) for p in ACTION_PREFIXES)

    # 1. Try official final result — strip attachments first
    final = _strip_attachments(agent_history.final_result() or "")
    if final and len(final.strip()) > 20 and not is_action_log(final):
        return final

    # 2. Try extracted_content — filter action logs and attachments
    try:
        extracted = _strip_attachments(agent_history.extracted_content() or "")
        if extracted:
            lines = [l for l in extracted.split('\n') if l.strip() and not is_action_log(l)]
            clean = "\n".join(lines).strip()
            if len(clean) > 20:
                return clean
    except Exception:
        pass

    # 3. Try action_results
    try:
        collected = []
        for r in agent_history.action_results():
            content = _strip_attachments(str(getattr(r, "extracted_content", "") or "").strip())
            if content and len(content) > 20 and not is_action_log(content):
                collected.append(content)
        if collected:
            return "\n\n".join(collected)
    except Exception:
        pass

    return ""


async def run_browser_task(task: str, task_type: str = "", task_id: str = "",
                           temporal: bool = False, max_steps: int = 25,
                           original_query: str = "") -> str:
    from backend.tools.learner import get_learned_context, learn_from_run
    learned_ctx = get_learned_context(original_query or task)
    browser = await get_browser()
    agent = _make_agent(task, browser, task_type, task_id, temporal, learned_ctx)
    history = await agent.run(max_steps=max_steps)
    result = _extract_best_result(history)
    steps = _step_logs.get(task_id, [])
    learn_from_run(original_query or task, steps, result, success=bool(result and len(result) > 20))
    return result


async def _rebuild_warm_browser() -> Browser:
    """Replace the shared warm browser with a fresh one after a broken session."""
    global _browser
    async with _browser_lock:
        if _browser is not None:
            try:
                await _browser.kill()
            except Exception:
                pass
        _browser = _make_browser(keep_alive=True)
        return _browser


async def _run_agent_once(task: str, browser: Browser, task_type: str, task_id: str,
                          temporal: bool, learned_ctx: str, max_steps: int) -> str:
    agent = _make_agent(task, browser, task_type, task_id, temporal, learned_ctx)
    history = await agent.run(max_steps=max_steps)
    return _extract_best_result(history)


async def run_deep_task(task: str, task_type: str = "", task_id: str = "",
                        temporal: bool = False, max_steps: int = 24,
                        original_query: str = "") -> str:
    """
    Run one browsing task, reusing the warm (already-launched) browser when it is
    free — the shared Chromium stays alive between queries (keep_alive=True), so
    only the very first query pays a cold start. The browser-use event bus
    self-heals on the next agent.run() → session.start().

    Concurrency: /browse tasks can overlap. Only one agent may drive the shared
    browser at a time, so if the warm browser is busy we transparently fall back
    to an isolated fresh browser for this task.
    """
    from backend.tools.learner import get_learned_context, learn_from_run

    learned_ctx = get_learned_context(original_query or task)

    # Try to claim the warm browser without blocking a concurrent task for long.
    got_warm = False
    try:
        await asyncio.wait_for(_warm_in_use.acquire(), timeout=0.05)
        got_warm = True
    except (asyncio.TimeoutError, Exception):
        got_warm = False

    result = ""
    try:
        if got_warm:
            browser = await get_browser()
            try:
                result = await _run_agent_once(task, browser, task_type, task_id,
                                               temporal, learned_ctx, max_steps)
            except Exception as e:
                # Warm session broke — rebuild it and retry once on a fresh browser.
                print(f"[Vayu] Warm browser run failed ({e}); rebuilding, retrying on fresh browser")
                await _rebuild_warm_browser()
                fresh = _make_browser(keep_alive=False)
                try:
                    result = await _run_agent_once(task, fresh, task_type, task_id,
                                                   temporal, learned_ctx, max_steps)
                finally:
                    try:
                        await fresh.kill()
                    except Exception:
                        pass
        else:
            # Warm browser busy with a concurrent task — use an isolated fresh browser.
            fresh = _make_browser(keep_alive=False)
            try:
                result = await _run_agent_once(task, fresh, task_type, task_id,
                                               temporal, learned_ctx, max_steps)
            finally:
                try:
                    await fresh.kill()
                except Exception:
                    pass
    finally:
        if got_warm:
            _warm_in_use.release()

    steps = _step_logs.get(task_id, [])
    learn_from_run(original_query or task, steps, result, success=bool(result and len(result) > 20))
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
