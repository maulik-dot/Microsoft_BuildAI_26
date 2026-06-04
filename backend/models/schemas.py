from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_USER = "waiting_user"


class TaskType(str, Enum):
    TRAVEL = "travel"
    JOBS = "jobs"
    PRICE_MONITOR = "price_monitor"
    HACKATHON = "hackathon"


# --- Travel ---
class TravelRequest(BaseModel):
    from_city: str
    to_city: str
    departure_date: str
    return_date: Optional[str] = None
    budget: Optional[float] = None
    preferences: Optional[str] = None


# --- Jobs ---
class JobRequest(BaseModel):
    job_titles: List[str]
    location: Optional[str] = None
    platforms: List[str] = ["linkedin", "naukri"]
    resume_text: Optional[str] = None


# --- Price Monitor ---
class PriceMonitorRequest(BaseModel):
    product_name: str
    target_price: float
    platforms: List[str] = ["amazon", "flipkart"]
    auto_buy: bool = False


# --- Hackathon ---
class HackathonRequest(BaseModel):
    resume_text: str
    skills: Optional[List[str]] = None
    background: Optional[str] = None
    platforms: List[str] = ["devfolio", "unstop", "hackerearth"]


# --- Generic Task ---
class TaskResponse(BaseModel):
    task_id: str
    task_type: TaskType
    status: TaskStatus
    result: Optional[dict] = None
    error: Optional[str] = None
    steps: List[str] = []
