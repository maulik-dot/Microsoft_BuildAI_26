import chainlit as cl
import httpx
import asyncio
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

API_BASE = os.environ.get("BACKEND_URL", f"http://localhost:{os.environ.get('PORT', '8000')}")

WELCOME = """**Agentic Web** — Ask me anything. I'll research it on the web for you.

Examples:
- *"Find flights from Mumbai to Delhi on June 15 under ₹8000"*
- *"Best Python developer jobs in Mumbai right now"*
- *"Is Samsung Galaxy S24 available under ₹55,000?"*
- *"Find hackathons for a BTech CSE engineer good at Python and ML"*
- *"What are the top AI startups in India in 2025?"*
- *"Find a Django course under ₹999 on Udemy and a free YouTube playlist"*

Just type anything — I'll figure out where to search."""


@cl.on_chat_start
async def start():
    cl.user_session.set("resume_text", None)
    cl.user_session.set("chat_history", [])
    await cl.Message(content=WELCOME).send()


@cl.on_message
async def handle_message(message: cl.Message):
    if message.elements:
        for el in message.elements:
            if hasattr(el, "path") and el.path.endswith(".pdf"):
                await handle_resume_upload(el.path, message.content)
                return

    query = message.content.strip()
    resume = cl.user_session.get("resume_text")
    if resume and any(w in query.lower() for w in ["job", "hackathon", "opportunity", "apply"]):
        query = f"{query}\n\nMy profile: {resume[:400]}"

    chat_history = cl.user_session.get("chat_history") or []
    await run_research(query, chat_history)


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
            f"Resume saved!\n\n**{profile.get('name', 'You')}** | {profile.get('current_role', 'N/A')}\n"
            f"**Skills:** {skills} | **Experience:** {profile.get('experience_years', 'N/A')} years\n\n"
            f"Now ask me anything — I'll use your profile for job/hackathon searches."
        )
        await msg.update()
        if message.strip():
            chat_history = cl.user_session.get("chat_history") or []
            await run_research(f"{message}\n\nMy profile: {data.get('resume_text','')[:400]}", chat_history)
    except Exception as e:
        msg.content = f"Resume parse failed: {e}"
        await msg.update()


async def run_research(query: str, chat_history: list):
    msg = cl.Message(content="🔍 Analysing your query...")
    await msg.send()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{API_BASE}/tasks/research",
                json={"query": query, "context": chat_history}
            )
            task = resp.json()
    except Exception as e:
        msg.content = f"❌ Failed to start: {e}"
        await msg.update()
        return

    task_id = task["task_id"]
    await poll_task(task_id, msg, query)


async def poll_task(task_id: str, msg: cl.Message, original_query: str):
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

            if status == "waiting_user":
                # ── Clarifying question flow ──────────────────────────────
                question = task.get("clarifying_question", "Could you clarify your request?")
                msg.content = f"❓ **I need one clarification before I start:**\n\n{question}"
                await msg.update()

                answer = await cl.AskUserMessage(content=question, timeout=120).send()
                if answer:
                    # Submit clarification to backend
                    try:
                        async with httpx.AsyncClient(timeout=10) as c:
                            await c.post(
                                f"{API_BASE}/tasks/{task_id}/answer",
                                json={"answer": answer["output"]},
                            )
                        msg.content = "🔍 Got it — researching now..."
                        await msg.update()
                    except Exception as e:
                        msg.content = f"❌ Failed to submit answer: {e}"
                        await msg.update()
                        return
                else:
                    msg.content = "⏱️ No answer received — task cancelled."
                    await msg.update()
                    return

            elif status == "completed":
                result = task.get("result") or {}
                answer_text = result.get("result") or "No result returned."
                confidence = task.get("confidence") or result.get("confidence")
                needs_review = task.get("needs_review") or result.get("needs_review", False)
                gaps = result.get("gaps", [])

                # Build confidence badge
                conf_badge = _confidence_badge(confidence)

                # Build review warning
                review_warning = ""
                if needs_review:
                    review_warning = "\n\n⚠️ **Low confidence — recommend verifying manually.**"
                    if gaps:
                        review_warning += f"\n*Missing: {', '.join(gaps[:2])}*"

                msg.content = f"🔍 **Research complete** {conf_badge}\n\n{answer_text}{review_warning}"
                await msg.update()

                # Update chat history
                history = cl.user_session.get("chat_history") or []
                history.append({"role": "user", "content": original_query})
                history.append({"role": "assistant", "content": answer_text})
                cl.user_session.set("chat_history", history[-10:])
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


def _confidence_badge(confidence: int | None) -> str:
    if confidence is None:
        return ""
    if confidence >= 80:
        return f"✅ `{confidence}% confidence`"
    elif confidence >= 60:
        return f"🟡 `{confidence}% confidence`"
    else:
        return f"🔴 `{confidence}% confidence`"
