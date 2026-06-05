from fastapi import APIRouter, BackgroundTasks, UploadFile, File, HTTPException
from pydantic import BaseModel
from backend.memory.agent_memory import _load as load_memory, _load_general, add_tip, mark_blocked, mark_works
from backend.tools.resume_parser import extract_text_from_pdf, parse_resume
import uuid, os

router = APIRouter(prefix="/tasks", tags=["tasks"])

task_store: dict = {}


class ResearchRequest(BaseModel):
    query: str


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


# --- General research endpoint ---

@router.post("/research")
async def start_research(request: ResearchRequest, background_tasks: BackgroundTasks):
    from backend.agents.research.agent import run_research

    task_id = str(uuid.uuid4())
    _new_task(task_id)

    async def run():
        _update(task_id, status="running")
        try:
            result = await run_research(request.query, task_id=task_id)
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
        except Exception as e:
            _update(task_id, status="failed", error=str(e))

    background_tasks.add_task(run)
    return task_store[task_id]


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


# --- Legacy specialized endpoints (kept for direct API use) ---

@router.post("/travel")
async def start_travel(request: dict, background_tasks: BackgroundTasks):
    from backend.agents.travel.crew import run_travel_booking
    from backend.models.schemas import TravelRequest

    task_id = str(uuid.uuid4())
    task_store[task_id] = {"task_id": task_id, "status": "pending", "result": None, "error": None}

    async def run():
        _update(task_id, status="running")
        try:
            result = await run_travel_booking(TravelRequest(**request))
            _update(task_id, status="completed", result=result)
        except Exception as e:
            _update(task_id, status="failed", error=str(e))

    background_tasks.add_task(run)
    return task_store[task_id]


@router.post("/jobs")
async def start_jobs(request: dict, background_tasks: BackgroundTasks):
    from backend.agents.jobs.crew import run_job_applications
    from backend.models.schemas import JobRequest

    task_id = str(uuid.uuid4())
    task_store[task_id] = {"task_id": task_id, "status": "pending", "result": None, "error": None}

    async def run():
        _update(task_id, status="running")
        try:
            result = await run_job_applications(JobRequest(**request))
            _update(task_id, status="completed", result=result)
        except Exception as e:
            _update(task_id, status="failed", error=str(e))

    background_tasks.add_task(run)
    return task_store[task_id]


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


@router.post("/hackathon")
async def start_hackathon(request: dict, background_tasks: BackgroundTasks):
    from backend.agents.hackathon.crew import find_hackathons
    from backend.models.schemas import HackathonRequest

    task_id = str(uuid.uuid4())
    task_store[task_id] = {"task_id": task_id, "status": "pending", "result": None, "error": None}

    async def run():
        _update(task_id, status="running")
        try:
            result = await find_hackathons(HackathonRequest(**request))
            _update(task_id, status="completed", result=result)
        except Exception as e:
            _update(task_id, status="failed", error=str(e))

    background_tasks.add_task(run)
    return task_store[task_id]


# --- Memory + status endpoints ---

@router.get("/evals")
async def get_evals():
    """Model performance baseline — shows pass rate, confidence, latency per model/task."""
    from backend.tools.model_selector import get_eval_report
    return get_eval_report()


@router.get("/memory")
async def get_memory():
    return {"task_memory": load_memory(), "general_memory": _load_general()}


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
