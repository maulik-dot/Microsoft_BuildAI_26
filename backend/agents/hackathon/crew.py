import asyncio
from backend.tools.browser import run_parallel_tasks
from backend.models.schemas import HackathonRequest
from backend.memory.agent_memory import get_context, update

DEEP_PROMPT = """You are a thorough research agent. Your job is to find hackathons on {url} for this developer:

PROFILE:
- Background: {background}
- Skills: {skills}
- Resume: {resume}

INSTRUCTIONS — follow every step carefully:

1. Navigate to https://{url}
2. Wait for the page to fully load
3. SCROLL DOWN slowly through the entire page — do not stop at the first few results
4. Keep scrolling until you reach the bottom or see at least 10+ hackathon cards
5. If there is a "Load More" button or pagination, click it and continue scrolling
6. For EACH hackathon card you see, click on it to open the full detail page
7. On the detail page extract EVERY piece of information:
   - Full name
   - Theme / problem statement / tracks
   - Total prize pool AND breakdown (1st, 2nd, 3rd prizes)
   - Registration deadline (exact date and time)
   - Hackathon dates (start and end)
   - Mode: online / offline / hybrid + location if offline
   - Team size (min and max)
   - Eligibility (students only? open to all? specific criteria?)
   - Who is organizing (company/college name)
   - Technologies/domains they want (AI, blockchain, web, etc.)
   - Any special perks (mentorship, swag, fast-track interviews)
   - Direct registration link
8. Go back and repeat for the next card
9. After collecting all details, SCORE each hackathon 1-10 based on:
   - Skill match with profile (Python, ML, React, etc.)
   - Prize value
   - Domain relevance
   - Accessibility (online preferred)
10. Return the TOP 8 ranked by score as a detailed numbered list

FORMAT each entry as:
---
N. [Name] — Score: X/10
Theme: ...
Prizes: ₹X (1st: ₹X, 2nd: ₹X)
Dates: [start] → [end] | Deadline: [date]
Mode: online/offline | Team: X-Y members
Eligibility: ...
Why it fits: [one sentence matching skills]
Register: [URL]
---

Be exhaustive. Do not summarize or skip details."""


async def find_hackathons(request: HackathonRequest, step_callback=None) -> dict:
    skills = ", ".join(request.skills) if request.skills else "Python, software engineering"
    platforms = request.platforms or ["devfolio", "unstop", "hackerearth"]

    platform_urls = {
        "devfolio": "devfolio.co/hackathons",
        "unstop": "unstop.com/hackathons",
        "hackerearth": "hackerearth.com/challenges/hackathon",
    }

    memory_ctx = get_context("hackathon")

    tasks = []
    for p in platforms:
        url = platform_urls.get(p, p)
        prompt = memory_ctx + "\n\n" + DEEP_PROMPT.format(
            url=url,
            background=request.background or "Software Engineer",
            skills=skills,
            resume=request.resume_text[:300],
        )
        tasks.append(prompt)

    results = await run_parallel_tasks(tasks, max_steps=30)

    sections = []
    for i, r in enumerate(results):
        if r:
            sections.append(f"## {platforms[i].upper()}\n\n{r}")

    combined = "\n\n---\n\n".join(sections)
    update("hackathon", combined, success=bool(combined))
    return {"result": combined, "platforms_searched": platforms}
