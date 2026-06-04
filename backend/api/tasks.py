from fastapi import APIRouter, BackgroundTasks, UploadFile, File, HTTPException
from backend.memory.agent_memory import _load as load_memory, add_tip, mark_blocked, mark_works
from backend.models.schemas import (
    TravelRequest, JobRequest, PriceMonitorRequest,
    HackathonRequest, TaskResponse, TaskStatus, TaskType
)
from backend.tools.resume_parser import extract_text_from_pdf, parse_resume
import uuid, os

router = APIRouter(prefix="/tasks", tags=["tasks"])

# In-memory task store (swap for DB in production)
task_store: dict[str, TaskResponse] = {}


def _update_task(task_id: str, **kwargs):
    if task_id in task_store:
        for k, v in kwargs.items():
            setattr(task_store[task_id], k, v)


@router.post("/travel", response_model=TaskResponse)
async def start_travel(request: TravelRequest, background_tasks: BackgroundTasks):
    from backend.agents.travel.crew import run_travel_booking

    task_id = str(uuid.uuid4())
    task = TaskResponse(task_id=task_id, task_type=TaskType.TRAVEL, status=TaskStatus.PENDING)
    task_store[task_id] = task

    async def run():
        _update_task(task_id, status=TaskStatus.RUNNING)
        try:
            result = await run_travel_booking(request)
            _update_task(task_id, status=TaskStatus.COMPLETED, result=result)
        except Exception as e:
            _update_task(task_id, status=TaskStatus.FAILED, error=str(e))

    background_tasks.add_task(run)
    return task


@router.post("/jobs", response_model=TaskResponse)
async def start_jobs(request: JobRequest, background_tasks: BackgroundTasks):
    from backend.agents.jobs.crew import run_job_applications

    task_id = str(uuid.uuid4())
    task = TaskResponse(task_id=task_id, task_type=TaskType.JOBS, status=TaskStatus.PENDING)
    task_store[task_id] = task

    async def run():
        _update_task(task_id, status=TaskStatus.RUNNING)
        try:
            result = await run_job_applications(request)
            _update_task(task_id, status=TaskStatus.COMPLETED, result=result)
        except Exception as e:
            _update_task(task_id, status=TaskStatus.FAILED, error=str(e))

    background_tasks.add_task(run)
    return task


@router.post("/price-monitor", response_model=TaskResponse)
async def start_price_monitor(request: PriceMonitorRequest, background_tasks: BackgroundTasks):
    from backend.agents.price_monitor.crew import check_price
    from backend.monitoring.scheduler import add_price_monitor

    task_id = str(uuid.uuid4())
    task = TaskResponse(task_id=task_id, task_type=TaskType.PRICE_MONITOR, status=TaskStatus.PENDING)
    task_store[task_id] = task

    async def run():
        _update_task(task_id, status=TaskStatus.RUNNING)
        try:
            result = await check_price(request)
            add_price_monitor(task_id, request.product_name, request.target_price, request.platforms)
            _update_task(task_id, status=TaskStatus.COMPLETED, result=result)
        except Exception as e:
            _update_task(task_id, status=TaskStatus.FAILED, error=str(e))

    background_tasks.add_task(run)
    return task


@router.post("/hackathon", response_model=TaskResponse)
async def start_hackathon(request: HackathonRequest, background_tasks: BackgroundTasks):
    from backend.agents.hackathon.crew import find_hackathons
    from backend.monitoring.scheduler import add_hackathon_monitor

    task_id = str(uuid.uuid4())
    task = TaskResponse(task_id=task_id, task_type=TaskType.HACKATHON, status=TaskStatus.PENDING)
    task_store[task_id] = task

    async def run():
        _update_task(task_id, status=TaskStatus.RUNNING)
        try:
            result = await find_hackathons(request)
            add_hackathon_monitor(task_id, request.resume_text, request.skills or [])
            _update_task(task_id, status=TaskStatus.COMPLETED, result=result)
        except Exception as e:
            _update_task(task_id, status=TaskStatus.FAILED, error=str(e))

    background_tasks.add_task(run)
    return task


@router.get("/memory")
async def get_memory():
    """See everything the agent has learned so far."""
    return load_memory()


@router.post("/memory/blocked")
async def add_blocked(task_type: str, domain: str):
    mark_blocked(task_type, domain)
    return {"status": "ok"}


@router.post("/memory/works")
async def add_works(task_type: str, domain: str):
    mark_works(task_type, domain)
    return {"status": "ok"}


@router.get("/{task_id}", response_model=TaskResponse)
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
