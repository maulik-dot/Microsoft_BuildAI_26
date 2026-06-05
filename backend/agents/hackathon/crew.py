from backend.tools.browser import run_parallel_tasks
from backend.tools.planner import plan_task
from backend.models.schemas import HackathonRequest
from backend.memory.agent_memory import update

TASK_TEMPLATE = """Find the best hackathons for this developer on {url}:

PROFILE:
- Background: {background}
- Skills: {skills}
- Resume: {resume}

SEARCH INSTRUCTIONS:
1. Navigate to https://{url}
2. Scroll slowly through the ENTIRE listings page — lazy load more by scrolling
3. Click "Load More" or pagination if available
4. For each hackathon card, click into it for full details
5. Extract from detail page:
   - Full name and organizer
   - Theme / tracks / problem domains
   - Total prize pool + breakdown (1st/2nd/3rd)
   - Registration deadline (exact date)
   - Event dates (start → end)
   - Mode: online / offline / hybrid + city if offline
   - Team size (min-max members)
   - Eligibility requirements
   - Technologies / domains they want
   - Any perks (mentorship, swag, fast-track hiring)
   - Direct registration URL
6. Score 1-10 vs the developer profile
7. Return TOP 8 ranked by score

FORMAT each as:
---
N. [Name] — Score: X/10
Organizer: ... | Mode: ... | Team: X-Y
Theme: ...
Prizes: ₹X total (1st: ₹X | 2nd: ₹X | 3rd: ₹X)
Dates: [start] → [end] | Deadline: [date]
Eligibility: ...
Why it fits: [one sentence]
Register: [URL]
---"""


async def find_hackathons(request: HackathonRequest, step_callback=None) -> dict:
    skills = ", ".join(request.skills) if request.skills else "Python, software engineering"
    platforms = request.platforms or ["devfolio", "unstop", "hackerearth"]

    platform_urls = {
        "devfolio": "devfolio.co/hackathons",
        "unstop": "unstop.com/hackathons",
        "hackerearth": "hackerearth.com/challenges/hackathon",
    }

    tasks = []
    for p in platforms:
        url = platform_urls.get(p, p)
        # Get a site-specific execution plan
        plan = plan_task(
            f"Find and rank hackathons on {url} for a {request.background or 'BTech CSE'} developer skilled in {skills}",
            "hackathon"
        )
        task = plan + TASK_TEMPLATE.format(
            url=url,
            background=request.background or "Software Engineer",
            skills=skills,
            resume=request.resume_text[:300],
        )
        tasks.append(task)

    results = await run_parallel_tasks(tasks, task_type="hackathon", max_steps=35)

    sections = [f"## {platforms[i].upper()}\n\n{r}" for i, r in enumerate(results) if r]
    combined = "\n\n---\n\n".join(sections)
    update("hackathon", combined, success=bool(combined))
    return {"result": combined, "platforms_searched": platforms}
