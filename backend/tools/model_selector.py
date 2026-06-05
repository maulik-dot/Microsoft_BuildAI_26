"""
Automatic model selector — tries models in priority order, picks the first one with quota.
Caches the working model in memory so we don't check on every call.
"""

import httpx
import time

# Priority order: fastest/cheapest first, most capable last as fallback
MODEL_PRIORITY = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-3.1-flash-image",
]

_cached_model: str | None = None
_cache_time: float = 0
CACHE_TTL = 300  # re-check every 5 minutes


def get_working_model() -> str:
    """Return the first model that has quota available."""
    global _cached_model, _cache_time

    # Use cached model if recent
    if _cached_model and (time.time() - _cache_time) < CACHE_TTL:
        return _cached_model

    from backend.config import settings
    key = settings.google_api_key
    for model in MODEL_PRIORITY:
        try:
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                json={"contents": [{"parts": [{"text": "hi"}]}]},
                timeout=5,
            )
            if "candidates" in r.json():
                _cached_model = model
                _cache_time = time.time()
                print(f"[ModelSelector] Using model: {model}")
                return model
        except Exception:
            continue

    # All models exhausted — return best available anyway (will fail gracefully)
    return "gemini-3.1-flash-lite"


def invalidate_model_cache():
    """Call this when a 429 is hit so we re-check models next time."""
    global _cached_model, _cache_time
    _cached_model = None
    _cache_time = 0
