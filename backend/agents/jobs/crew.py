from backend.tools.browser import run_parallel_tasks
from backend.tools.planner import plan_task
from backend.models.schemas import JobRequest
from backend.memory.agent_memory import update

TASK_TEMPLATE = """Search for "{title}" jobs on {url} in {location}.

SEARCH INSTRUCTIONS:
1. Go to https://{url}
2. Type "{title}" in the search bar, set location to "{location}"
3. Sort by: Most Recent
4. Scroll through at least 2 pages of results
5. For each job click into it and extract:
   - Exact job title
   - Company name + size/type if shown
   - Location (city / remote / hybrid)
   - Salary range (exact)
   - Experience required
   - Key skills required (list all)
   - Job description highlights
   - Date posted
   - Application type (Easy Apply / External)
   - Direct apply URL
6. Also search for "{title_alt}" and add any new results
7. Collect 8 best matches total, ranked by: salary → recency → relevance

Resume to match against: {resume}

FORMAT each job as:
---
N. [Title] at [Company]
Location: ... | Salary: ₹X-Y LPA | Exp: X-Y yrs
Skills: ...
Posted: ... | Apply: Easy/External
Why it fits: [one line]
URL: [apply link]
---"""


async def run_job_applications(request: JobRequest, step_callback=None) -> dict:
    platforms = request.platforms or ["naukri"]
    title = request.job_titles[0]
    title_alt = request.job_titles[1] if len(request.job_titles) > 1 else f"Senior {title}"

    platform_urls = {
        "naukri": "naukri.com",
        "linkedin": "linkedin.com/jobs",
        "indeed": "indeed.co.in",
    }

    tasks = []
    for p in platforms:
        url = platform_urls.get(p, p)
        plan = plan_task(
            f"Find {title} jobs in {request.location or 'India'} on {url}",
            "jobs"
        )
        task = plan + TASK_TEMPLATE.format(
            url=url,
            title=title,
            title_alt=title_alt,
            location=request.location or "India",
            resume=(request.resume_text or "Not provided")[:300],
        )
        tasks.append(task)

    results = await run_parallel_tasks(tasks, task_type="jobs", max_steps=30)

    sections = [f"## {platforms[i].upper()}\n\n{r}" for i, r in enumerate(results) if r]
    combined = "\n\n---\n\n".join(sections)
    update("jobs", combined, success=bool(combined))
    return {"summary": combined, "titles": request.job_titles, "platforms": platforms}
