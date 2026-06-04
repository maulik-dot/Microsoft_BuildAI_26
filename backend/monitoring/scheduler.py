from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

scheduler = AsyncIOScheduler()


def start_scheduler():
    if not scheduler.running:
        scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()


def add_price_monitor(monitor_id: str, product: str, target_price: float, platforms: list, interval_minutes: int = 30):
    from backend.agents.price_monitor.crew import check_price
    from backend.models.schemas import PriceMonitorRequest

    async def job():
        req = PriceMonitorRequest(product_name=product, target_price=target_price, platforms=platforms)
        result = await check_price(req)
        print(f"[Price Monitor] {product}: {result}")

    scheduler.add_job(
        job,
        "interval",
        minutes=interval_minutes,
        id=f"price_{monitor_id}",
        replace_existing=True,
    )


def add_hackathon_monitor(monitor_id: str, resume_text: str, skills: list, interval_hours: int = 6):
    from backend.agents.hackathon.crew import find_hackathons
    from backend.models.schemas import HackathonRequest

    async def job():
        req = HackathonRequest(resume_text=resume_text, skills=skills)
        result = await find_hackathons(req)
        print(f"[Hackathon Monitor] New results: {result}")

    scheduler.add_job(
        job,
        "interval",
        hours=interval_hours,
        id=f"hackathon_{monitor_id}",
        replace_existing=True,
    )


def remove_monitor(monitor_id: str):
    try:
        scheduler.remove_job(monitor_id)
    except Exception:
        pass
