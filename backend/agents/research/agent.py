"""
General-purpose web research agent.
Takes any natural language query, plans a search strategy, browses the web, returns a structured answer.
"""

from backend.tools.browser import run_deep_task
from backend.tools.planner import plan_research
from backend.memory.agent_memory import get_general_context, update_general


RESEARCH_SYSTEM = """You are a world-class web researcher. Given any question or task, you:
1. Start with Google Search to find the best sources
2. Navigate to the most relevant pages
3. Extract thorough, accurate information
4. Cross-reference across multiple sources when needed
5. Return a clean, structured, comprehensive answer

You NEVER give up after one failed attempt. You try multiple search queries and sources."""


async def run_research(query: str) -> dict:
    """Run a general-purpose research task on any query."""

    # Get learned context from memory
    memory_ctx = get_general_context(query)

    # Generate a research plan using Gemini
    plan = plan_research(query)

    task = f"""{memory_ctx}

RESEARCH QUERY: {query}

{plan}

RESEARCH INSTRUCTIONS:
1. Start by going to https://www.google.com and searching for the most relevant query
2. Open the top 3-5 most relevant results
3. Extract all useful information from each page
4. If one source doesn't have enough info, go back to Google and search differently
5. Cross-reference facts across sources for accuracy
6. If the query involves prices/availability (products, flights, hotels), go directly to relevant sites
7. If the query involves people/companies, check their official site + Wikipedia + news
8. If the query involves events/opportunities (jobs, hackathons, courses), check multiple listing platforms

HANDLING OBSTACLES:
- Cookie banners: click Accept immediately
- Login walls: close popup and continue browsing
- Paywalls: go back to Google and find a different source
- Slow pages: wait 3 seconds and scroll

OUTPUT FORMAT:
Structure your answer clearly with:
- A direct answer to the query upfront (1-2 sentences)
- Detailed findings organized in sections
- Tables or lists where data is comparative
- Sources/URLs for every major claim
- A "Key Takeaway" or recommendation at the end

Be thorough. The user wants the BEST possible answer, not a quick summary."""

    result = await run_deep_task(task, task_type="research", max_steps=40)
    update_general(query, result, success=bool(result))

    return {
        "query": query,
        "result": result,
    }
