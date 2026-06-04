import asyncio
from backend.tools.browser import run_parallel_tasks
from backend.models.schemas import JobRequest
from backend.memory.agent_memory import get_context, update

DEEP_PROMPT = """You are a thorough job research agent. Search for jobs on {url}.

SEARCH CRITERIA:
- Job title: {title}
- Location: {location}
- Resume summary: {resume}

INSTRUCTIONS — be exhaustive:

1. Go to https://{url}
2. Search for "{title}" in {location}
3. SORT results by: Most Recent (click the sort option if available)
4. SCROLL through at least 2-3 pages of results
5. For each job listing, click into it and extract:
   - Exact job title
   - Company name + company size/type if shown
   - Location (city / remote / hybrid)
   - Salary range (exact numbers, not ranges if possible)
   - Experience required (years)
   - Key skills required
   - Job description highlights (what they actually need)
   - Date posted
   - Application type: Easy Apply / External / Direct
   - Direct apply URL
6. Also try a SECOND search with a variation: "{title_alt}"
7. Collect top 8 most relevant jobs total
8. Rank them by: salary → relevance to resume → recency

FORMAT each job as:
---
N. [Title] at [Company]
Location: ... | Salary: ₹X-Y LPA | Experience: X yrs
Skills needed: ...
Posted: ... | Apply type: Easy Apply / External
Why it fits: [one line]
Apply: [URL]
---

Do not skip any job. Click into each one."""


async def run_job_applications(request: JobRequest, step_callback=None) -> dict:
    platforms = request.platforms or ["naukri", "indeed"]
    ordered = sorted(platforms, key=lambda p: 0 if p == "naukri" else 1)

    platform_urls = {
        "naukri": "naukri.com",
        "linkedin": "linkedin.com/jobs",
        "indeed": "indeed.co.in",
    }

    memory_ctx = get_context("jobs")
    title = request.job_titles[0]
    title_alt = request.job_titles[1] if len(request.job_titles) > 1 else f"Senior {title}"

    tasks = []
    for p in ordered:
        url = platform_urls.get(p, p)
        prompt = memory_ctx + "\n\n" + DEEP_PROMPT.format(
            url=url,
            title=title,
            title_alt=title_alt,
            location=request.location or "India",
            resume=(request.resume_text or "Not provided")[:300],
        )
        tasks.append(prompt)

    results = await run_parallel_tasks(tasks, max_steps=28)

    sections = []
    for i, r in enumerate(results):
        if r:
            sections.append(f"## {ordered[i].upper()}\n\n{r}")

    combined = "\n\n---\n\n".join(sections)
    update("jobs", combined, success=bool(combined))
    return {"summary": combined, "titles": request.job_titles, "platforms": ordered}
