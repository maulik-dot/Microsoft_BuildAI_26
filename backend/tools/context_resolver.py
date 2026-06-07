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
    # Pronouns
    "their", "them", "those", "these", "its", "it",
    # Specific item references
    "the book", "the books", "the first", "the second", "the third",
    "that one", "which one", "the job", "the jobs", "the product",
    "the course", "the flight", "the hotel", "the price", "the prices",
    "the video", "the channel", "the playlist", "the problem",
    "the result", "the link", "the page", "the site",
    "all of them", "any of them", "the last one", "the same",
    # Follow-up signals
    "what about", "how about", "and also", "compare them",
    "cheaper", "better", "different", "free", "paid", "similar",
    # Conditional signals — always send to LLM for branch resolution
    "if the ", "if it ", "if there", "if not", "otherwise",
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

    prompt = f"""You are resolving a follow-up question in a conversation.

CONVERSATION HISTORY:
{conv_text}

NEW MESSAGE FROM USER: "{query}"

Decision rules (apply strictly in order):

1. CONDITIONAL IF/ELSE: If the message says "If [condition], do X. If not, do Y":
   - Check the conversation history to evaluate whether the condition is true or false
   - If the condition IS met → rewrite as just "do X" (with specific context filled in)
   - If the condition is NOT met (or the referenced thing doesn't exist) → rewrite as just "do Y" (with specific context)
   - Example: "If the video has >50k views, find playlist. If not, search GeeksforGeeks."
     → If history shows no video was found → resolve to "Search GeeksforGeeks for [topic from context]"
     → If history shows video with 100k views → resolve to "Find the most popular DSA playlist on [channel name]"

2. NEW TOPIC: If the message introduces a completely different subject/domain, return UNCHANGED.

3. FOLLOW-UP WITH PRONOUNS: If "their", "it", "the same", "which one" directly refers to items from previous message, name those items explicitly.

4. STANDALONE: If already specific and standalone, return UNCHANGED.

Return ONLY the final resolved question. No explanation."""

    resolved = _call_llm(prompt, task_type="planning")
    if not resolved or len(resolved.strip()) < 3:
        return query

    resolved = resolved.strip().strip('"').strip("'")

    # Sanity check — if resolution is way too long or clearly wrong, fall back
    if len(resolved) > 500 or not resolved:
        return query

    return resolved
