import chainlit as cl
import httpx
import asyncio
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

API_BASE = "http://localhost:8000"

WELCOME = """**Agentic Web** — Ask me anything. I'll research it on the web for you.

Examples:
- *"Find flights from Mumbai to Delhi on June 15 under ₹8000"*
- *"Best Python developer jobs in Mumbai right now"*
- *"Is Samsung Galaxy S24 available under ₹55,000?"*
- *"Find hackathons for a BTech CSE engineer good at Python and ML"*
- *"What are the top AI startups in India in 2025?"*
- *"Compare iPhone 15 vs Samsung S24 — which is better value?"*
- *"Best online courses for machine learning under ₹5000"*

Just type anything — I'll figure out where to search and find the best answer."""


@cl.on_chat_start
async def start():
    cl.user_session.set("resume_text", None)
    await cl.Message(content=WELCOME).send()


@cl.on_message
async def handle_message(message: cl.Message):
    # Handle PDF resume uploads
    if message.elements:
        for el in message.elements:
            if hasattr(el, "path") and el.path.endswith(".pdf"):
                await handle_resume_upload(el.path, message.content)
                return

    query = message.content.strip()

    # Inject resume context if available and relevant
    resume = cl.user_session.get("resume_text")
    if resume and any(w in query.lower() for w in ["job", "hackathon", "opportunity", "apply", "hire"]):
        query = f"{query}\n\nMy profile: {resume[:400]}"

    await run_research(query)


async def handle_resume_upload(path: str, message: str):
    msg = cl.Message(content="Parsing your resume...")
    await msg.send()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            with open(path, "rb") as f:
                resp = await client.post(
                    f"{API_BASE}/tasks/upload-resume",
                    files={"file": (os.path.basename(path), f, "application/pdf")},
                )
        data = resp.json()
        profile = data.get("profile", {})
        cl.user_session.set("resume_text", data.get("resume_text", ""))
        skills = ", ".join(profile.get("skills", [])[:6])
        msg.content = (
            f"Resume saved!\n\n"
            f"**{profile.get('name', 'You')}** | {profile.get('current_role', 'N/A')}\n"
            f"**Skills:** {skills}\n"
            f"**Experience:** {profile.get('experience_years', 'N/A')} years\n\n"
            f"Now ask me anything — I'll use your profile automatically for job/hackathon searches."
        )
        await msg.update()

        # If there was a message alongside the upload, research it
        if message.strip():
            await run_research(f"{message}\n\nMy profile: {data.get('resume_text','')[:400]}")
    except Exception as e:
        msg.content = f"Resume parse failed: {e}"
        await msg.update()


async def run_research(query: str):
    msg = cl.Message(content="🔍 Researching...")
    await msg.send()

    # Start research task
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{API_BASE}/tasks/research", json={"query": query})
            task = resp.json()
    except Exception as e:
        msg.content = f"❌ Failed to start: {e}"
        await msg.update()
        return

    task_id = task["task_id"]
    dots = 0

    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                resp = await client.get(f"{API_BASE}/tasks/{task_id}")
                task = resp.json()
            except Exception:
                await asyncio.sleep(2)
                continue

            status = task["status"]

            if status == "completed":
                result = task.get("result") or {}
                answer = result.get("result") or result.get("summary") or "No result returned."
                msg.content = f"🔍 **Research complete**\n\n{answer}"
                await msg.update()
                break
            elif status == "failed":
                msg.content = f"❌ **Failed:** {task.get('error', 'Unknown error')}"
                await msg.update()
                break
            else:
                dots = (dots % 3) + 1
                msg.content = f"🔍 Browsing the web{'.' * dots}"
                await msg.update()
                await asyncio.sleep(2)
