"""
Context Resolver — resolves follow-up queries using conversation history.

Examples:
  History: "Find Django courses under ₹999 on Udemy"
  New query: "what about free ones?"
  Resolved: "Find free Django courses on YouTube or other free platforms"

  History: "Compare Samsung S24 prices on Flipkart and Amazon"
  New query: "which one should I buy?"
  Resolved: "Based on the Samsung S24 price comparison on Flipkart and Amazon, which one offers better value to buy?"
"""

from backend.tools.planner import _call_llm


def resolve_query(query: str, context: list[dict]) -> str:
    """
    If the query is a follow-up (uses pronouns, references previous topic),
    resolve it into a fully standalone question using conversation history.

    If the query is self-contained, return it unchanged.
    """
    if not context:
        return query

    # Quick check — if query is clearly standalone, skip resolution
    standalone_signals = len(query.split()) > 8 and not any(
        w in query.lower() for w in [
            "it", "that", "those", "them", "this", "these",
            "what about", "how about", "same", "also", "too",
            "another", "more", "else", "instead", "other",
            "cheaper", "better", "different", "free", "paid"
        ]
    )
    if standalone_signals:
        return query

    # Build conversation summary (last 6 turns max)
    recent = context[-6:]
    conv_lines = []
    for msg in recent:
        role = "User" if msg.get("role") == "user" else "Agent"
        content = str(msg.get("content", ""))[:200]
        conv_lines.append(f"{role}: {content}")

    conv_text = "\n".join(conv_lines)

    prompt = f"""You are resolving a follow-up question in a conversation.

CONVERSATION SO FAR:
{conv_text}

NEW MESSAGE FROM USER: "{query}"

Task: If the new message is a follow-up that references something from the conversation (using pronouns, comparisons, or implicit references), rewrite it as a fully standalone question that makes sense without the conversation context.

If the message is already standalone and self-contained, return it exactly as-is.

Rules:
- Keep the rewritten question natural and concise
- Preserve the user's original intent
- Don't add information that wasn't implied
- Return ONLY the resolved question, nothing else

Examples:
- "what about free ones?" after Django course search → "Find free Django courses on YouTube or other platforms"
- "which is better value?" after price comparison → "Based on the Samsung S24 comparison, which offers better value: Flipkart or Amazon?"
- "find me Python jobs in Mumbai" (standalone) → "find me Python jobs in Mumbai"

Resolved question:"""

    resolved = _call_llm(prompt, task_type="planning")
    if not resolved or len(resolved.strip()) < 3:
        return query

    resolved = resolved.strip().strip('"').strip("'")
    return resolved if resolved else query
