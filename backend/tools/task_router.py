"""
Task Router — self-learning, zero hardcoded site lists.

Routes queries to either chit-chat or the universal browser agent.
The browser agent discovers and learns which sites and flows work — no pre-programmed lists.
"""

import json
from backend.tools.planner import _call_llm


def classify(query: str, context: list = None) -> str:
    """Classify the query into either browser_agent or chit_chat."""
    from datetime import datetime
    today = datetime.now().strftime("%B %d, %Y")

    history_str = ""
    if context:
        history_str = "CONVERSATION HISTORY:\n" + "\n".join(
            f"{'User' if m.get('role') == 'user' else 'Vayu'}: {m.get('content', '')}"
            for m in context[-6:]
        ) + "\n\n"

    prompt = f"""Classify this user query into exactly one category. Return ONLY the category name.

Today's date: {today}

{history_str}User Query: "{query}"

- chit_chat: casual messages, greetings, pleasantries, compliments, thanks, simple conversational replies, personal questions (like name, identity, feelings), or chat that does not require web search. Key signals: "hi", "hello", "hey", "thanks", "thank you", "arigato", "good job", "great", "nice", "bye", "what is my name", "who are you".

- browser_agent: EVERYTHING ELSE — any query that benefits from live web browsing, source discovery, comparison, extraction, or verification.

Return only: browser_agent | chit_chat"""

    result = _call_llm(prompt, task_type="planning")
    result = result.strip().lower().split()[0] if result else "browser_agent"
    valid = {"browser_agent", "chit_chat"}
    return result if result in valid else "browser_agent"


async def route(query: str, task_id: str = "", context: list = None) -> dict:
    task_type = classify(query, context=context)

    if task_type == "chit_chat":
        # Format recent conversation history
        history_str = ""
        if context:
            history_str = "\n".join(
                f"{'User' if m.get('role') == 'user' else 'Vayu'}: {m.get('content', '')}"
                for m in context[-6:]
            ) + "\n"

        # Reply directly without browser
        reply = _call_llm(f"""You are Vayu, a friendly and helpful autonomous browser agent. 
Reply politely and concisely to the user's message, keeping the conversation history in mind. Stay in character.

CONVERSATION HISTORY:
{history_str}
USER MESSAGE: "{query}"

Return only your direct reply.""", task_type="planning")
        return {
            "query": query,
            "result": reply,
            "task_type": "chit_chat",
            "confidence": 100,
            "needs_review": False,
            "gaps": [],
            "status": "completed"
        }

    from backend.agents.research.agent import run_research
    res = await run_research(query, task_id=task_id)

    from backend.tools.rich_cards import enrich_response
    return await enrich_response(query, res)


# ── Param parsers ──────────────────────────────────────────────────────────

def _parse_travel(query: str) -> dict:
    from datetime import datetime
    year = datetime.now().year
    raw = _call_llm(f"""Extract travel params from: "{query}"
JSON: {{"from_city": "...", "to_city": "...", "departure_date": "YYYY-MM-DD", "return_date": null, "budget": null}}
Assume year {year} if not specified. JSON only.""", task_type="planning")
    try:
        params = _parse_json(raw)
        params.setdefault("from_city", "Mumbai")
        params.setdefault("to_city", "Delhi")
        params.setdefault("departure_date", f"{year}-06-15")
        return params
    except Exception:
        return {"from_city": "Mumbai", "to_city": "Delhi", "departure_date": f"{year}-06-15"}


def _parse_json(raw: str) -> dict:
    if not raw: return {}
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw.strip())
