import asyncio
from browser_use import Agent, Browser, BrowserProfile
from browser_use.llm.google.chat import ChatGoogle
from backend.config import settings

_browser: Browser | None = None
_browser_lock = asyncio.Lock()


def get_llm():
    return ChatGoogle(
        model="gemini-3.1-flash-lite",
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


async def run_browser_task(task: str, step_callback=None, max_steps: int = 25) -> str:
    """Single-phase task using the warm persistent browser."""
    browser = await get_browser()
    agent = Agent(
        task=task,
        llm=get_llm(),
        browser=browser,
        llm_timeout=60,
        step_timeout=90,
    )
    result = await agent.run(max_steps=max_steps)
    return result.final_result() or ""


async def run_deep_task(task: str, max_steps: int = 35) -> str:
    """Deep research task — gets its own browser instance for isolation."""
    browser = _make_browser(keep_alive=False)
    agent = Agent(
        task=task,
        llm=get_llm(),
        browser=browser,
        llm_timeout=60,
        step_timeout=120,
    )
    result = await agent.run(max_steps=max_steps)
    await browser.close()
    return result.final_result() or ""


async def run_parallel_tasks(tasks: list[str], max_steps: int = 25) -> list[str]:
    """Run multiple tasks in parallel — each gets its own browser."""
    async def _run_one(task: str) -> str:
        browser = _make_browser(keep_alive=False)
        agent = Agent(task=task, llm=get_llm(), browser=browser, llm_timeout=60, step_timeout=120)
        result = await agent.run(max_steps=max_steps)
        await browser.close()
        return result.final_result() or ""

    return await asyncio.gather(*[_run_one(t) for t in tasks])


async def close_browser():
    global _browser
    if _browser:
        await _browser.close()
        _browser = None
