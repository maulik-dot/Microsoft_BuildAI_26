"""
Provider-aware LLM helpers.

Model names are routed by shape:
  • names containing "/"  → OpenRouter (OpenAI-compatible), e.g. "openai/gpt-4o-mini"
  • bare names            → Google Gemini directly,          e.g. "gemini-3.1-flash-lite"

This lets the model router mix Gemini (primary) and OpenRouter (fallback) models in
the same tier lists — every consumer just asks for a model name and this module talks
to the right provider. Errors are raised (never swallowed) so the caller's cooldown /
candidate-rotation logic (model_selector.note_error) can react.
"""

from backend.config import settings

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
# Optional OpenRouter attribution headers (used for their dashboard rankings).
_OR_HEADERS = {"HTTP-Referer": "https://vayu.app", "X-Title": "Vayu"}


def is_openrouter(model: str) -> bool:
    """OpenRouter slugs are namespaced ('provider/model'); Gemini names are bare."""
    return "/" in model


def make_browser_llm(model: str, temperature: float = 0):
    """
    Build a browser_use chat LLM for the given model name, picking the provider from
    the name. Used for both the primary and fallback agent LLMs — every model listed
    for either tier must be vision-capable, since the agent sends screenshots.
    """
    if is_openrouter(model):
        from browser_use.llm.openai.chat import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=settings.openrouter_api_key,
            base_url=OPENROUTER_BASE,
            temperature=temperature,
            default_headers=_OR_HEADERS,
        )
    from browser_use.llm.google.chat import ChatGoogle
    return ChatGoogle(model=model, api_key=settings.google_api_key, temperature=temperature)


def complete_text(model: str, prompt: str) -> str:
    """
    One-shot text completion, provider-aware. Returns the stripped text.
    Raises on failure (HTTP error, quota, etc.) so callers can note_error() and rotate.
    """
    if is_openrouter(model):
        import httpx
        r = httpx.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
                **_OR_HEADERS,
            },
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()   # 429/404/... → HTTPStatusError whose text carries the code
        return (r.json()["choices"][0]["message"]["content"] or "").strip()

    from google import genai
    client = genai.Client(api_key=settings.google_api_key)
    r = client.models.generate_content(model=model, contents=prompt)
    return (r.text or "").strip()
