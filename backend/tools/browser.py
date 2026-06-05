import asyncio
from browser_use import Agent, Browser, BrowserProfile
from browser_use.llm.google.chat import ChatGoogle
from backend.config import settings

_browser: Browser | None = None
_browser_lock = asyncio.Lock()


def get_llm():
    # Priority: Gemini (free quota) > OpenAI (if funded)
    from backend.tools.model_selector import get_working_model
    return ChatGoogle(
        model=get_working_model(),
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


def _make_agent(task: str, browser: Browser, task_type: str = "") -> Agent:
    """Create an agent with full human-browsing context injected into every step."""
    from backend.tools.context import get_system_context
    return Agent(
        task=task,
        llm=get_llm(),
        browser=browser,
        llm_timeout=60,
        step_timeout=120,
        extend_system_message=get_system_context(task_type),
    )


async def run_browser_task(task: str, task_type: str = "", step_callback=None, max_steps: int = 25) -> str:
    """Single task using the warm persistent browser."""
    browser = await get_browser()
    agent = _make_agent(task, browser, task_type)
    result = await agent.run(max_steps=max_steps)
    return result.final_result() or ""


async def run_deep_task(task: str, task_type: str = "", max_steps: int = 40) -> str:
    """Deep research task — own browser instance for isolation."""
    browser = _make_browser(keep_alive=False)
    try:
        agent = _make_agent(task, browser, task_type)
        result = await agent.run(max_steps=max_steps)
        return result.final_result() or ""
    finally:
        await browser.close()


async def run_parallel_tasks(tasks: list[str], task_type: str = "", max_steps: int = 25) -> list[str]:
    """Run tasks sequentially on the warm shared browser."""
    browser = await get_browser()
    results = []
    for task in tasks:
        try:
            agent = _make_agent(task, browser, task_type)
            result = await agent.run(max_steps=max_steps)
            results.append(result.final_result() or "")
        except Exception as e:
            results.append(f"Error: {e}")
    return results


async def close_browser():
    global _browser
    if _browser:
        await _browser.close()
        _browser = None
