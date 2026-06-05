import asyncio
from browser_use import Agent, Browser, BrowserProfile
from browser_use.llm.google.chat import ChatGoogle
from backend.config import settings

_browser: Browser | None = None
_browser_lock = asyncio.Lock()

# Global step log store: task_id -> list of step dicts
_step_logs: dict[str, list[dict]] = {}


def get_llm():
    from backend.tools.model_selector import get_model_for_tier, ModelTier
    return ChatGoogle(
        model=get_model_for_tier(ModelTier.LARGE),
        api_key=settings.google_api_key,
        temperature=0,
    )


def _make_browser(keep_alive: bool = True) -> Browser:
    return Browser(
        browser_profile=BrowserProfile(
            headless=False,
            disable_security=True,
            keep_alive=keep_alive,
            minimum_wait_page_load_time=0.5,
            wait_between_actions=0.3,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        )
    )


async def get_browser() -> Browser:
    global _browser
    async with _browser_lock:
        if _browser is None:
            _browser = _make_browser(keep_alive=True)
    return _browser


def _make_agent(task: str, browser: Browser, task_type: str = "", task_id: str = "") -> Agent:
    from backend.tools.context import get_system_context

    def on_step(browser_state, agent_output, step_number):
        """Capture each step and store it for real-time frontend polling."""
        try:
            # Extract URL being visited
            url = ""
            if browser_state and hasattr(browser_state, 'url'):
                url = browser_state.url or ""

            # Extract action taken
            action_name = ""
            action_detail = ""
            if agent_output and hasattr(agent_output, 'action'):
                actions = agent_output.action or []
                if actions:
                    first = actions[0]
                    action_name = type(first).__name__.lower().replace('action', '')
                    # Try to get the URL or text from the action
                    for attr in ('url', 'query', 'text', 'selector'):
                        val = getattr(first, attr, None)
                        if val:
                            action_detail = str(val)[:80]
                            break

            # Extract memory/next_goal for user-friendly description
            description = ""
            if agent_output:
                if hasattr(agent_output, 'next_goal') and agent_output.next_goal:
                    description = str(agent_output.next_goal)[:120]
                elif hasattr(agent_output, 'thinking') and agent_output.thinking:
                    description = str(agent_output.thinking)[:120]

            step = {
                "step": step_number,
                "url": url,
                "action": action_name,
                "detail": action_detail,
                "description": description,
            }

            if task_id:
                _step_logs.setdefault(task_id, [])
                _step_logs[task_id].append(step)

        except Exception:
            pass

    return Agent(
        task=task,
        llm=get_llm(),
        browser=browser,
        llm_timeout=60,
        step_timeout=120,
        extend_system_message=get_system_context(task_type),
        register_new_step_callback=on_step,
    )


def get_steps(task_id: str) -> list[dict]:
    """Return accumulated step logs for a task."""
    return _step_logs.get(task_id, [])


def clear_steps(task_id: str):
    _step_logs.pop(task_id, None)


def _extract_best_result(agent_history) -> str:
    """
    Extract the best available result from agent history.
    Falls back gracefully if final_result() is empty.
    """
    # Try the official final result first
    final = agent_history.final_result()
    if final and len(final.strip()) > 50:
        return final

    # Fallback: use the built-in extracted_content() method
    try:
        extracted = agent_history.extracted_content()
        if extracted and len(extracted.strip()) > 20:
            return extracted
    except Exception:
        pass

    # Fallback: collect from action_results
    try:
        collected = []
        for r in agent_history.action_results():
            content = getattr(r, 'extracted_content', None)
            if content and len(str(content).strip()) > 20:
                collected.append(str(content).strip())
        if collected:
            return "\n\n".join(collected)
    except Exception:
        pass

    return ""


async def run_browser_task(task: str, task_type: str = "", task_id: str = "",
                           step_callback=None, max_steps: int = 25) -> str:
    browser = await get_browser()
    agent = _make_agent(task, browser, task_type, task_id)
    result = await agent.run(max_steps=max_steps)
    return _extract_best_result(result)


async def run_deep_task(task: str, task_type: str = "", task_id: str = "",
                        max_steps: int = 40) -> str:
    browser = _make_browser(keep_alive=False)
    try:
        agent = _make_agent(task, browser, task_type, task_id)
        result = await agent.run(max_steps=max_steps)
        return _extract_best_result(result)
    finally:
        await browser.close()


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
