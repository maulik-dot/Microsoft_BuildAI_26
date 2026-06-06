"""
Context Resolver — resolves follow-up queries using conversation history.

Key fix: when a follow-up uses pronouns ("their", "them", "those", "its")
or references ("the books", "these jobs", "the first one"), extract the
specific items from the previous agent response and name them explicitly.

Examples:
  History: agent listed "Verity by Colleen Hoover, Gone Girl by Gillian Flynn, The Silent Patient"
  Follow-up: "what are their prices?"
  Resolved: "What are the prices of Verity by Colleen Hoover, Gone Girl by Gillian Flynn, and The Silent Patient?"

  History: agent found "Python Developer at TCS ₹8L, Software Engineer at Infosys"
  Follow-up: "which one has better growth?"
  Resolved: "Between Python Developer at TCS and Software Engineer at Infosys, which has better growth?"
"""

from backend.tools.planner import _call_llm


REFERENCE_WORDS = [
    "their", "them", "those", "these", "its", "it",
    "the book", "the books", "the first", "the second", "the third",
    "that one", "which one", "the job", "the jobs", "the product",
    "the course", "the flight", "the hotel", "the price", "the prices",
    "all of them", "any of them", "the last one", "the same",
    "what about", "how about", "and also", "compare them",
    "cheaper", "better", "different", "free", "paid", "similar",
]


def resolve_query(query: str, context: list[dict]) -> str:
    """
    Resolve follow-up queries using full conversation context.
    Extracts specific named items from previous agent responses
    so the agent doesn't lose track of what was discussed.
    """
    if not context:
        return query

    q_lower = query.lower()

    # Quick check — if standalone query, return as-is
    has_reference = any(w in q_lower for w in REFERENCE_WORDS)
    is_short = len(query.split()) <= 10
    is_follow_up = has_reference or is_short

    if not is_follow_up and len(query.split()) > 10:
        return query

    # Get the last 6 turns
    recent = context[-6:]

    # Build conversation text — include full agent responses for entity extraction
    conv_lines = []
    for msg in recent:
        role = "User" if msg.get("role") == "user" else "Vayu (agent)"
        content = str(msg.get("content", ""))[:800]  # enough to capture names/titles
        conv_lines.append(f"{role}: {content}")

    conv_text = "\n".join(conv_lines)

    prompt = f"""You are resolving a follow-up question in a conversation. The user may reference things from previous messages using pronouns or vague terms.

CONVERSATION HISTORY:
{conv_text}

NEW MESSAGE FROM USER: "{query}"

Your task:
1. Identify what specific items/entities the user is referring to (books, jobs, products, prices, etc.)
2. Extract their EXACT names/titles from the conversation history
3. Rewrite the user's message as a fully standalone question that explicitly names those items

Rules:
- If the previous agent response listed specific items (books, jobs, prices, products), NAME THEM in the resolved query
- Do not be vague — "their prices" must become "prices of [exact item names]"
- Keep the user's original intent intact
- If the query is already standalone and specific, return it unchanged
- Return ONLY the resolved question, nothing else

Examples of good resolution:
- "what are their prices?" after listing 3 books → "What are the current prices of [Book 1], [Book 2], and [Book 3] on Amazon or Flipkart?"
- "which is cheaper?" after price comparison → "Between [Product A at ₹X] and [Product B at ₹Y], which is the cheaper option?"
- "find me Python jobs in Mumbai" (standalone) → "find me Python jobs in Mumbai" (unchanged)

Resolved question:"""

    resolved = _call_llm(prompt, task_type="planning")
    if not resolved or len(resolved.strip()) < 3:
        return query

    resolved = resolved.strip().strip('"').strip("'")

    # Sanity check — if resolution is way too long or clearly wrong, fall back
    if len(resolved) > 500 or not resolved:
        return query

    return resolved
