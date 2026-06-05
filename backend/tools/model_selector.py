"""
Model Router — two-tier selection with eval tracking.

Principles:
1. Establish performance baseline via evals (tracked in model_evals.json)
2. Use best models for accuracy-critical tasks (browser agent, complex research)
3. Optimize cost/latency by routing simple tasks to smaller models
4. Never prematurely limit — always fall back to larger model if small one fails

Tiers:
  SMALL — fast, cheap: planning, parsing, verification, clarifying questions
  LARGE — best available: browser agent, multi-step reasoning, deep research
"""

import httpx
import time
import json
import os
from enum import Enum

# ── Model Tiers ──────────────────────────────────────────────────────────────

class ModelTier(str, Enum):
    SMALL = "small"   # Planning, parsing, verification, classification
    LARGE = "large"   # Browser automation, complex multi-step research

# Small = fast + cheap. Sufficient for structured tasks with clear inputs.
SMALL_MODELS = [
    "gemini-3.1-flash-lite",     # 500 req/day free — primary small model
    "gemini-flash-lite-latest",  # alias fallback
    "gemini-2.0-flash-lite",     # secondary small fallback
]

# Large = most capable available. Used when reasoning quality matters.
LARGE_MODELS = [
    "gemini-2.5-flash",          # Best reasoning, 20 req/day free
    "gemini-3.5-flash",          # Second best, 20 req/day free
    "gemini-2.0-flash",          # Solid, higher quota
    "gemini-3.1-flash-lite",     # Fallback if large models exhausted
]

# Task → Tier routing table
# Add new task types here as the agent grows
TASK_TIER_MAP = {
    # Small tasks — structured output, low stakes
    "ambiguity_check":    ModelTier.SMALL,
    "planning":           ModelTier.SMALL,
    "verification":       ModelTier.SMALL,
    "resume_parsing":     ModelTier.SMALL,
    "replan":             ModelTier.SMALL,

    # Large tasks — open-ended reasoning, browser navigation
    "browser_agent":      ModelTier.LARGE,
    "deep_research":      ModelTier.LARGE,
    "cross_service":      ModelTier.LARGE,
}

# ── Cache ─────────────────────────────────────────────────────────────────────

_cache: dict[str, tuple[str, float]] = {}  # tier -> (model, timestamp)
CACHE_TTL = 300  # 5 minutes


def get_model(task_type: str = "browser_agent") -> str:
    """Return the best available model for a given task type."""
    tier = TASK_TIER_MAP.get(task_type, ModelTier.LARGE)
    return get_model_for_tier(tier)


def get_model_for_tier(tier: ModelTier) -> str:
    """Return the best working model for a tier, with caching."""
    global _cache

    # Check cache
    if tier in _cache:
        model, ts = _cache[tier]
        if time.time() - ts < CACHE_TTL:
            return model

    from backend.config import settings
    key = settings.google_api_key

    models = SMALL_MODELS if tier == ModelTier.SMALL else LARGE_MODELS

    for model in models:
        try:
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                json={"contents": [{"parts": [{"text": "hi"}]}]},
                timeout=5,
            )
            if "candidates" in r.json():
                _cache[tier] = (model, time.time())
                print(f"[ModelRouter] {tier.value.upper()} → {model}")
                return model
        except Exception:
            continue

    # All exhausted — return the cheapest model anyway
    fallback = SMALL_MODELS[0]
    print(f"[ModelRouter] WARNING: all {tier.value} models exhausted, using {fallback}")
    return fallback


def invalidate(tier: ModelTier | None = None):
    """Invalidate cache for a tier (or all tiers) after a 429."""
    global _cache
    if tier:
        _cache.pop(tier, None)
    else:
        _cache.clear()


# Backward-compatible alias used by browser.py
def get_working_model() -> str:
    return get_model_for_tier(ModelTier.LARGE)


# ── Eval Tracker ──────────────────────────────────────────────────────────────

EVAL_FILE = os.path.join(os.path.dirname(__file__), "../../../model_evals.json")


def record_eval(task_type: str, model: str, passed: bool, confidence: int, latency_ms: int = 0):
    """
    Record a model eval result. Builds the performance baseline over time.
    Use this to diagnose where smaller models succeed vs fail.
    """
    evals = _load_evals()

    key = f"{task_type}:{model}"
    entry = evals.setdefault(key, {
        "task_type": task_type,
        "model": model,
        "tier": TASK_TIER_MAP.get(task_type, ModelTier.LARGE).value,
        "runs": 0,
        "passed": 0,
        "total_confidence": 0,
        "total_latency_ms": 0,
    })

    entry["runs"] += 1
    if passed:
        entry["passed"] += 1
    entry["total_confidence"] += confidence
    entry["total_latency_ms"] += latency_ms

    # Derived metrics
    entry["pass_rate"] = round(entry["passed"] / entry["runs"], 2)
    entry["avg_confidence"] = round(entry["total_confidence"] / entry["runs"])
    entry["avg_latency_ms"] = round(entry["total_latency_ms"] / entry["runs"])

    _save_evals(evals)


def get_eval_report() -> dict:
    """Return a summary of model performance across all task types."""
    evals = _load_evals()
    report = {}
    for key, entry in evals.items():
        report[key] = {
            "tier": entry.get("tier"),
            "runs": entry["runs"],
            "pass_rate": entry.get("pass_rate", 0),
            "avg_confidence": entry.get("avg_confidence", 0),
            "avg_latency_ms": entry.get("avg_latency_ms", 0),
            "recommendation": _recommend(entry),
        }
    return report


def _recommend(entry: dict) -> str:
    """Suggest whether to upgrade or downgrade model for this task type."""
    pass_rate = entry.get("pass_rate", 0)
    tier = entry.get("tier", "large")
    if pass_rate >= 0.9 and tier == "large":
        return "✅ Consider downgrading to small model — pass rate is high"
    elif pass_rate < 0.7 and tier == "small":
        return "⬆️ Upgrade to large model — small model failing too often"
    elif pass_rate >= 0.9:
        return "✅ Model performing well — no change needed"
    else:
        return f"⚠️ Pass rate {pass_rate:.0%} — monitor closely"


def _load_evals() -> dict:
    if os.path.exists(EVAL_FILE):
        try:
            with open(EVAL_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_evals(evals: dict):
    try:
        with open(EVAL_FILE, "w") as f:
            json.dump(evals, f, indent=2)
    except Exception:
        pass
