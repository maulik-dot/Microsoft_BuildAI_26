import chainlit as cl
import httpx
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

API_BASE = "http://localhost:8000"

WELCOME = """**Agentic Web** — Your autonomous web agent

I can handle:
- **Travel** → *"Find flights from Mumbai to Delhi, June 10-12, under ₹8000"*
- **Jobs** → *"Find Python developer jobs on LinkedIn and Naukri"*
- **Price Monitor** → *"Alert me when iPhone 15 drops below ₹60,000 on Flipkart"*
- **Hackathons** → *"Find hackathons for a BTech CSE engineer skilled in Python and ML"*

You can also **upload your resume** and I'll auto-fill your profile for job and hackathon searches.

What would you like me to do?"""


@cl.on_chat_start
async def start():
    cl.user_session.set("resume_profile", None)
    await cl.Message(content=WELCOME).send()


@cl.on_message
async def handle_message(message: cl.Message):
    # Handle resume file uploads
    if message.elements:
        for el in message.elements:
            if hasattr(el, "path") and el.path.endswith(".pdf"):
                await handle_resume_upload(el.path)
                return

    await route_message(message.content)


async def handle_resume_upload(path: str):
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
        cl.user_session.set("resume_profile", data.get("resume_text", ""))
        skills = ", ".join(profile.get("skills", [])[:6])
        msg.content = f"Resume parsed!\n\n**Name:** {profile.get('name', 'N/A')}\n**Skills:** {skills}\n**Experience:** {profile.get('experience_years', 'N/A')} years\n\nYour profile is saved. Ask me to find jobs or hackathons and I'll use it automatically."
        await msg.update()
    except Exception as e:
        msg.content = f"Failed to parse resume: {e}"
        await msg.update()


async def route_message(text: str):
    """Use Gemini to parse intent and extract params from natural language."""
    msg = cl.Message(content="Thinking...")
    await msg.send()

    # Parse intent with Gemini
    try:
        intent_data = await parse_intent(text)
    except Exception as e:
        msg.content = f"⚠️ {e}"
        await msg.update()
        return

    if not intent_data or not intent_data.get("intent"):
        msg.content = "I can help with **travel**, **jobs**, **price monitoring**, or **hackathon discovery**. Could you be more specific?"
        await msg.update()
        return

    intent = intent_data.get("intent")
    params = intent_data.get("params", {})

    # Inject saved resume if available
    resume_text = cl.user_session.get("resume_profile")
    if resume_text and intent in ("jobs", "hackathon"):
        params["resume_text"] = resume_text

    endpoint_map = {
        "travel": "/tasks/travel",
        "jobs": "/tasks/jobs",
        "price_monitor": "/tasks/price-monitor",
        "hackathon": "/tasks/hackathon",
    }

    endpoint = endpoint_map.get(intent)
    if not endpoint:
        msg.content = "I can help with travel, jobs, price monitoring, or hackathon discovery."
        await msg.update()
        return

    # Start task
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{API_BASE}{endpoint}", json=params)
            task = resp.json()
    except Exception as e:
        msg.content = f"Failed to start task: {e}"
        await msg.update()
        return

    task_id = task["task_id"]
    icon = {"travel": "✈️", "jobs": "💼", "price_monitor": "🔔", "hackathon": "🏆"}.get(intent, "🤖")
    msg.content = f"{icon} Agent started — browsing the web for you..."
    await msg.update()

    # Poll and stream updates
    await poll_task(task_id, msg, icon)


async def parse_intent(user_text: str) -> dict | None:
    """Use Gemini to extract structured intent from natural language."""
    from google import genai as google_genai
    client = google_genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))

    prompt = f"""Extract the intent and parameters from this message. Return ONLY valid JSON.

Message: "{user_text}"

Possible intents:
- "travel": needs from_city, to_city, departure_date (YYYY-MM-DD), optional return_date, budget (number in INR)
- "jobs": needs job_titles (list), optional location, platforms (list from: linkedin, naukri, indeed)
- "price_monitor": needs product_name, target_price (number in INR), optional platforms (list from: amazon, flipkart), auto_buy (boolean, default false)
- "hackathon": needs resume_text (use "not provided" if unknown), optional skills (list), background (e.g. "BTech CSE"), platforms (list from: devfolio, unstop, hackerearth, default all three)

Return format:
{{"intent": "...", "params": {{...}}}}

If message doesn't match any intent, return: {{"intent": null, "params": {{}}}}"""

    try:
        response = client.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        # Surface the real error so it shows in the UI
        raise RuntimeError(f"Intent parsing failed: {e}") from e


async def poll_task(task_id: str, msg: cl.Message, icon: str):
    """Poll task status and update message as it progresses."""
    dots = 0
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                resp = await client.get(f"{API_BASE}/tasks/{task_id}")
                task = resp.json()
            except Exception:
                await asyncio.sleep(3)
                continue

            status = task["status"]

            if status == "completed":
                result = task.get("result", {})
                summary = result.get("summary") or result.get("result") or str(result)
                msg.content = f"{icon} **Done!**\n\n{summary}"
                await msg.update()
                break
            elif status == "failed":
                error = task.get("error", "Unknown error")
                msg.content = f"❌ **Failed:** {error}"
                await msg.update()
                break
            else:
                dots = (dots % 3) + 1
                msg.content = f"{icon} Agent working{'.' * dots}"
                await msg.update()
                await asyncio.sleep(2)
