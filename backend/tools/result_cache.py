"""
Result cache — coarse, reliable "trajectory reuse".

Instead of replaying browser steps (fragile: browser-use element indices are assigned
per page-load, so a recorded "click [34]" won't map next run), we reuse the *outcome*
of a completed query and skip the whole browse when the same query repeats.

- Keyed on the normalized (resolved) query.
- TTL-bounded, with a SHORT TTL for volatile queries (flights, live prices, stocks…)
  so we never serve badly-stale data, and a longer TTL for stable research.
- Persisted to JSON (survives within a container; attach a volume to persist across
  restarts). Best-effort — any failure just means a cache miss.
"""

import json
import os
import re
import time

CACHE_FILE = os.path.join(os.path.dirname(__file__), "../memory/result_cache.json")

STABLE_TTL = 12 * 3600     # 12h — jobs, hackathons, general research, "what is X"
VOLATILE_TTL = 20 * 60     # 20m — anything price/fare/live that goes stale fast
MAX_ENTRIES = 200

# Query looks time-sensitive → keep its cached answer only briefly.
_VOLATILE = (
    "flight", "fare", "airfare", "stock", "share price", "crypto", "bitcoin",
    "weather", "score", "live", "today", "right now", "tonight", "cheapest",
    "price", "current price", "in stock", "availability", "deal", "discount",
    "offer", "near me",
)


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _ttl_for(query: str) -> int:
    ql = _norm(query)
    return VOLATILE_TTL if any(w in ql for w in _VOLATILE) else STABLE_TTL


def _answer_text(result) -> str:
    if not isinstance(result, dict):
        return ""
    r = result.get("result")
    if isinstance(r, dict):
        return r.get("answer") or ""
    return r or ""


def cacheable(result) -> bool:
    """Only cache real, completed answers — not clarifications, errors, or thin replies."""
    return (
        isinstance(result, dict)
        and result.get("status") == "completed"
        and result.get("task_type") != "chit_chat"
        and len(_answer_text(result)) >= 40
    )


def _load() -> dict:
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        pass


def get(query: str):
    """Return a still-fresh cached result for this query, or None."""
    key = _norm(query)
    if not key:
        return None
    entry = _load().get(key)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > entry.get("ttl", STABLE_TTL):
        return None
    return entry.get("result")


def put(query: str, result) -> None:
    """Store a completed result under the normalized query (best-effort)."""
    key = _norm(query)
    if not key or not cacheable(result):
        return
    data = _load()
    data[key] = {"result": result, "ts": time.time(), "ttl": _ttl_for(query)}
    if len(data) > MAX_ENTRIES:                       # evict oldest
        for k in sorted(data, key=lambda k: data[k].get("ts", 0))[: len(data) - MAX_ENTRIES]:
            data.pop(k, None)
    _save(data)
