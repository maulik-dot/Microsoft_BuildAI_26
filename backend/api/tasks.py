from fastapi import APIRouter, BackgroundTasks, UploadFile, File, HTTPException
from pydantic import BaseModel
from backend.memory.agent_memory import _load as load_memory, _load_general, add_tip, mark_blocked, mark_works
from backend.tools.resume_parser import extract_text_from_pdf, parse_resume
import uuid, os, asyncio

router = APIRouter(prefix="/tasks", tags=["tasks"])

task_store: dict = {}
# Maps task_id → asyncio.Task so we can cancel it
_running_tasks: dict[str, asyncio.Task] = {}


class ResearchRequest(BaseModel):
    query: str
    context: list[dict] = []  # [{role: "user"|"agent", content: "..."}]


class AnswerRequest(BaseModel):
    answer: str


class TaskResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None
    error: str | None = None


def _update(task_id: str, **kwargs):
    if task_id in task_store:
        task_store[task_id].update(kwargs)


def _new_task(task_id: str, **kwargs) -> dict:
    record = {"task_id": task_id, "status": "pending", "result": None,
              "error": None, "confidence": None, "needs_review": False,
              "clarifying_question": None, **kwargs}
    task_store[task_id] = record
    return record


# --- Universal browser-agent endpoint ---

@router.post("/browse")
async def start_research(request: ResearchRequest, background_tasks: BackgroundTasks):
    from backend.agents.research.agent import run_research

    task_id = str(uuid.uuid4())
    _new_task(task_id)

    async def run():
        # Register this coroutine as a cancellable task
        current = asyncio.current_task()
        if current:
            _running_tasks[task_id] = current

        _update(task_id, status="running")
        try:
            from backend.tools.task_router import route
            from backend.tools.context_resolver import resolve_query

        # Resolve follow-up context before routing.
            resolved_query = await asyncio.get_event_loop().run_in_executor(
                None, resolve_query, request.query, request.context
            )

            result = await route(resolved_query, task_id=task_id, context=request.context)
            if result.get("status") == "waiting_user":
                _update(task_id,
                    status="waiting_user",
                    result=result,
                    clarifying_question=result.get("clarifying_question"))
            else:
                _update(task_id,
                    status="completed",
                    result=result,
                    confidence=result.get("confidence", 50),
                    needs_review=result.get("needs_review", False))
        except asyncio.CancelledError:
            _update(task_id, status="stopped", error="Stopped by user.")
        except Exception as e:
            _update(task_id, status="failed", error=str(e))
        finally:
            _running_tasks.pop(task_id, None)

    background_tasks.add_task(run)
    return task_store[task_id]


@router.post("/{task_id}/stop")
async def stop_task(task_id: str):
    """Cancel a running task immediately."""
    if task_id not in task_store:
        raise HTTPException(status_code=404, detail="Task not found")

    task = _running_tasks.get(task_id)
    if task and not task.done():
        task.cancel()
        _update(task_id, status="stopped", error="Stopped by user.")
        # Also stop the browser agent if mid-run
        try:
            from backend.tools.browser import get_steps, clear_steps
            clear_steps(task_id)
        except Exception:
            pass
        return {"status": "stopped"}

    status = task_store[task_id].get("status", "unknown")
    return {"status": status, "message": "Task was not running"}


@router.post("/{task_id}/answer")
async def answer_clarification(task_id: str, request: AnswerRequest, background_tasks: BackgroundTasks):
    """Resume a waiting_user task with the user's clarification answer."""
    from backend.agents.research.agent import run_research

    if task_id not in task_store:
        raise HTTPException(status_code=404, detail="Task not found")

    task = task_store[task_id]
    original_query = task.get("result", {}).get("query", "")
    refined_query = f"{original_query} [clarification: {request.answer}]"

    _update(task_id, status="running", clarifying_question=None)

    async def run():
        try:
            result = await run_research(refined_query, task_id=task_id)
            _update(task_id,
                status="completed",
                result=result,
                confidence=result.get("confidence", 50),
                needs_review=result.get("needs_review", False))
        except Exception as e:
            _update(task_id, status="failed", error=str(e))

    background_tasks.add_task(run)
    return task_store[task_id]


# --- Price Monitor endpoint (kept for direct API use) ---

@router.post("/price-monitor")
async def start_price_monitor(request: dict, background_tasks: BackgroundTasks):
    from backend.agents.price_monitor.crew import check_price
    from backend.models.schemas import PriceMonitorRequest

    task_id = str(uuid.uuid4())
    task_store[task_id] = {"task_id": task_id, "status": "pending", "result": None, "error": None}

    async def run():
        _update(task_id, status="running")
        try:
            result = await check_price(PriceMonitorRequest(**request))
            _update(task_id, status="completed", result=result)
        except Exception as e:
            _update(task_id, status="failed", error=str(e))

    background_tasks.add_task(run)
    return task_store[task_id]



# --- Memory + status endpoints ---

@router.get("/models")
async def get_model_status():
    """
    Live-check quota status for all configured models.
    Returns availability, tier, daily limit, and usage from evals.
    """
    import httpx
    from backend.config import settings
    from backend.tools.model_selector import SMALL_MODELS, LARGE_MODELS, TASK_TIER_MAP, _load_evals

    key = settings.google_api_key
    evals = _load_evals()

    all_models = {
        "gemini-3.1-flash-lite": {"limit": 500,  "tier": "small"},
        "gemini-flash-lite-latest": {"limit": 500,  "tier": "small"},
        "gemini-2.0-flash-lite":    {"limit": 500,  "tier": "small"},
        "gemini-2.5-flash":         {"limit": 20,   "tier": "large"},
        "gemini-3.5-flash":         {"limit": 20,   "tier": "large"},
        "gemini-2.0-flash":         {"limit": 200,  "tier": "large"},
        "gemini-3.1-flash-image":   {"limit": 20,   "tier": "large"},
        # OpenRouter fallbacks — separate quota pool, reached once Gemini cools down
        "openai/gpt-4o-mini":           {"limit": 0, "tier": "small", "provider": "openrouter"},
        "google/gemini-2.5-flash-lite": {"limit": 0, "tier": "small", "provider": "openrouter"},
        "openai/gpt-4o":                {"limit": 0, "tier": "large", "provider": "openrouter"},
        "google/gemini-2.5-flash":      {"limit": 0, "tier": "large", "provider": "openrouter"},
    }

    results = []
    for model, meta in all_models.items():
        status = "unknown"
        # OpenRouter fallbacks: don't probe (each probe is a paid call). The key was
        # validated at setup; report them as available standby capacity.
        if meta.get("provider") == "openrouter":
            status = "available" if settings.openrouter_api_key else "not_found"
        else:
          try:
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                json={"contents": [{"parts": [{"text": "hi"}]}]},
                timeout=5,
            )
            d = r.json()
            if "candidates" in d:
                status = "available"
            elif d.get("error", {}).get("code") == 429:
                status = "exhausted"
            elif d.get("error", {}).get("code") == 404:
                status = "not_found"
            else:
                status = "error"
          except Exception:
            status = "unreachable"

        # Get usage from eval tracker
        eval_runs = 0
        for k, v in evals.items():
            if model in k:
                eval_runs += v.get("runs", 0)

        results.append({
            "model": model,
            "tier": meta["tier"],
            "daily_limit": meta["limit"],
            "status": status,
            "eval_runs": eval_runs,
            "is_primary": (
                model == SMALL_MODELS[0] and meta["tier"] == "small"
            ) or (
                model == LARGE_MODELS[0] and meta["tier"] == "large"
            ),
        })

    return {
        "models": results,
        "quota_resets": "midnight UTC (~5:30 AM IST)",
        "key_hint": f"...{key[-6:]}" if key else "not set",
    }


@router.get("/knowledge")
async def get_knowledge():
    """Full web knowledge base — sites, navigation hints, search patterns, shortcuts."""
    from backend.tools.learner import _load
    return _load()


@router.post("/knowledge/seed")
async def seed_knowledge(request: dict):
    """
    Manually teach the agent about a site — no browsing needed.
    Body: {
      "site": "ixigo.com",
      "category": "travel",
      "navigation_hint": "Enter city in From/To fields, wait for dropdown, click Search",
      "tips": ["Flights load in 3-5s", "Non-stop filter on left panel"],
      "works_for": ["flight search", "hotel search"]
    }
    """
    from backend.tools.learner import _load, _save
    knowledge = _load()

    site = request.get("site", "").strip().lower()
    if not site:
        return {"error": "site is required"}

    # Clean domain
    import re
    site = re.sub(r'^(https?://)?(www\.)?', '', site).split('/')[0]

    sites_node = knowledge.setdefault("sites", {})
    entry = sites_node.setdefault(site, {
        "success_count": 0, "fail_count": 0,
        "avg_steps": 0, "total_steps": 0, "runs": 0,
        "tips": [], "navigation_hint": "", "page_flows": {},
        "last_seen": None,
    })

    if request.get("navigation_hint"):
        entry["navigation_hint"] = request["navigation_hint"][:200]

    if request.get("tips"):
        existing_tips = entry.get("tips", [])
        for tip in request["tips"]:
            if tip not in existing_tips:
                existing_tips.append(tip)
        entry["tips"] = existing_tips[:10]

    # Record a reusable flow instead of a domain shortcut.
    if request.get("navigation_hint") or request.get("tips"):
        flow_bucket = entry.setdefault("page_flows", {}).setdefault("manual_seed", [])
        flow_bucket.append({
            "summary": request.get("navigation_hint", "manual seed"),
            "steps": request.get("tips", [])[:5],
            "result": request.get("category", ""),
            "success": True,
        })
        entry["page_flows"]["manual_seed"] = flow_bucket[-5:]

    if request.get("works_for"):
        entry["best_for"] = list(dict.fromkeys((entry.get("best_for", []) + [w.lower() for w in request["works_for"]])))[:8]

    # Boost success count for seeded sites
    entry["success_count"] = max(entry.get("success_count", 0), 2)

    _save(knowledge)
    return {"status": "seeded", "site": site, "entry": entry}


@router.post("/knowledge/correct")
async def correct_knowledge(request: dict):
    """
    Submit a correction when the agent got something wrong.
    Body: {
      "query": "find cheapest flights Mumbai Delhi",
      "what_went_wrong": "Agent tried MakeMyTrip which blocked it",
      "correct_approach": "Go directly to ixigo.com/flights, don't use MakeMyTrip",
      "bad_site": "makemytrip.com",
      "good_site": "ixigo.com"
    }
    The agent learns from this correction immediately.
    """
    from backend.tools.learner import _load, _save
    from backend.memory.agent_memory import mark_blocked, mark_works
    knowledge = _load()

    query = request.get("query", "")
    what_went_wrong = request.get("what_went_wrong", "")
    correct_approach = request.get("correct_approach", "")
    bad_site = request.get("bad_site", "").strip().lower()
    good_site = request.get("good_site", "").strip().lower()

    # Mark bad site as failed
    if bad_site:
        import re
        bad_site = re.sub(r'^(https?://)?(www\.)?', '', bad_site).split('/')[0]
        sites_node = knowledge.setdefault("sites", {})
        bad_entry = sites_node.setdefault(bad_site, {"success_count": 0, "fail_count": 0, "runs": 0})
        bad_entry["fail_count"] = bad_entry.get("fail_count", 0) + 2  # weight corrections more
        mark_blocked("research", bad_site)

    # Mark good site as working
    if good_site:
        import re
        good_site = re.sub(r'^(https?://)?(www\.)?', '', good_site).split('/')[0]
        sites_node = knowledge.setdefault("sites", {})
        good_entry = sites_node.setdefault(good_site, {"success_count": 0, "fail_count": 0, "runs": 0})
        good_entry["success_count"] = good_entry.get("success_count", 0) + 2
        mark_works("research", good_site)

    # Store correction as an obstacle solution
    if what_went_wrong and correct_approach:
        solutions = knowledge.setdefault("obstacle_solutions", [])
        from datetime import datetime
        solutions.append({
            "obstacle": what_went_wrong,
            "solution": correct_approach,
            "query_example": query[:100],
            "bad_site": bad_site,
            "good_site": good_site,
            "source": "human_correction",
            "date": datetime.now().strftime("%Y-%m-%d"),
        })
        knowledge["obstacle_solutions"] = solutions[-30:]

    # Add correct approach as navigation hint for good site
    if good_site and correct_approach:
        sites_node = knowledge.setdefault("sites", {})
        entry = sites_node.setdefault(good_site, {"success_count": 2, "fail_count": 0})
        if not entry.get("navigation_hint"):
            entry["navigation_hint"] = correct_approach[:200]
        flow_bucket = entry.setdefault("page_flows", {}).setdefault("manual_correction", [])
        flow_bucket.append({
            "summary": correct_approach[:200],
            "steps": [what_went_wrong[:80]] if what_went_wrong else [],
            "result": query[:120],
            "success": True,
        })
        entry["page_flows"]["manual_correction"] = flow_bucket[-5:]

    _save(knowledge)
    return {
        "status": "correction recorded",
        "bad_site_penalized": bad_site or None,
        "good_site_boosted": good_site or None,
        "lesson_saved": bool(what_went_wrong and correct_approach),
    }


@router.delete("/knowledge/reset")
async def reset_knowledge():
    """Reset the web knowledge base (useful for testing)."""
    from backend.tools.learner import _save
    _save({
        "sites": {}, "web_patterns": {}, "query_patterns": {},
        "obstacle_solutions": [],
        "last_updated": None,
    })
    return {"status": "knowledge base reset"}


@router.get("/evals")
async def get_evals():
    """Model performance baseline — shows pass rate, confidence, latency per model/task."""
    from backend.tools.model_selector import get_eval_report
    return get_eval_report()


@router.get("/memory")
async def get_memory():
    return {"task_memory": load_memory(), "general_memory": _load_general()}


@router.get("/{task_id}/steps")
async def get_steps(task_id: str):
    """Real-time step log for a running task."""
    from backend.tools.browser import get_steps as _get_steps
    return {"task_id": task_id, "steps": _get_steps(task_id)}


@router.get("/{task_id}")
async def get_task(task_id: str):
    if task_id not in task_store:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_store[task_id]


@router.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    os.makedirs("uploads", exist_ok=True)
    path = f"uploads/{file.filename}"
    with open(path, "wb") as f:
        f.write(await file.read())
    text = extract_text_from_pdf(path)
    profile = parse_resume(text)
    return {"resume_text": text, "profile": profile}
