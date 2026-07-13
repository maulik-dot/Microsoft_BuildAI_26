"""
Model Router — two-tier selection with eval tracking.

Principles:
1. Establish performance baseline via evals (tracked in model_evals.json)
2. Use best models for accuracy-critical tasks (browser agent, complex browsing)
3. Optimize cost/latency by routing simple tasks to smaller models
4. Never prematurely limit — always fall back to larger model if small one fails

Tiers:
  SMALL — fast, cheap: planning, parsing, verification, clarifying questions
  LARGE — best available: browser agent, multi-step reasoning, deep browsing
"""

import asyncio
import httpx
import time
import json
import os
from enum import Enum

# ── Model Tiers ──────────────────────────────────────────────────────────────

class ModelTier(str, Enum):
    SMALL = "small"   # Planning, parsing, verification, classification
    LARGE = "large"   # Browser automation, complex multi-step browsing

# Model names decide the provider (see llm_client): bare = Gemini (direct key),
# "provider/model" = OpenRouter. OpenRouter models are listed LAST in each tier so
# they're only reached once the direct-key Gemini models are all cooling down (429).
# Every model here must be vision-capable — both tiers can drive the screenshot agent.

# Small = fast + cheap. Sufficient for structured tasks with clear inputs.
SMALL_MODELS = [
    "gemini-3.1-flash-lite",     # 500 req/day free — primary small model
    "gemini-flash-lite-latest",  # alias fallback
    "gemini-2.0-flash-lite",     # secondary small fallback
    # ── OpenRouter fallbacks (separate quota pool) ──
    "openai/gpt-4o-mini",            # cheap, reliable, vision + structured output
    "google/gemini-2.5-flash-lite",  # Gemini via OpenRouter — dodges direct-key 429
]

# Large = most capable available. Used when reasoning quality matters.
LARGE_MODELS = [
    "gemini-3.1-flash-lite",     # High rate limit — most reliable for long tasks
    "gemini-2.5-flash",          # Best reasoning when available
    "gemini-3.5-flash",          # Only 5 req/min on some keys — fallback
    "gemini-2.0-flash",          # Additional fallback
    # ── OpenRouter fallbacks (separate quota pool) ──
    "openai/gpt-4o",             # strong vision agent model
    "google/gemini-2.5-flash",   # Gemini via OpenRouter — dodges direct-key 429
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

# ── Reactive availability (no per-request network probes) ─────────────────────
#
# The previous design ran a BLOCKING httpx probe (5s timeout, sequential) against
# Google's generateContent endpoint on every cache miss — on the request hot path,
# in an async server, once per tier every 5 minutes. Worse, each probe spent a real
# generateContent call just to say "hi", burning scarce quota (gemini-2.5-flash is
# ~20 req/day). We removed that entirely:
#
#   • get_model* are now instant and non-blocking — they return the startup-resolved
#     model for a tier, or the primary, skipping any model on cooldown.
#   • resolve_models() does ONE parallel async probe at startup (off the hot path).
#   • real call failures feed back via note_error() → a short cooldown, so an
#     exhausted (429) or nonexistent (404) model is skipped without re-probing.

_resolved: dict[ModelTier, str] = {}   # tier -> validated working model (set at startup)
_cooldown: dict[str, float] = {}       # model -> unix ts when it may be retried

EXHAUSTED_COOLDOWN = 900    # 429 / rate limit → retry in 15 min
UNAVAILABLE_COOLDOWN = 3600  # 404 / unknown model → retry in 1 hour


def _available(model: str) -> bool:
    ts = _cooldown.get(model)
    return ts is None or time.time() >= ts


def mark_exhausted(model: str):
    """Model hit a rate/quota limit (429) — skip it for a while."""
    _cooldown[model] = time.time() + EXHAUSTED_COOLDOWN
    print(f"[ModelRouter] {model} exhausted → cooldown {EXHAUSTED_COOLDOWN}s")


def mark_unavailable(model: str):
    """Model not found / unusable on this key (404) — skip it longer."""
    _cooldown[model] = time.time() + UNAVAILABLE_COOLDOWN
    print(f"[ModelRouter] {model} unavailable → cooldown {UNAVAILABLE_COOLDOWN}s")


def note_error(model: str, err) -> None:
    """Classify a real LLM call error and cool the model down accordingly."""
    msg = str(err).lower()
    if any(s in msg for s in ("429", "resource_exhausted", "rate limit", "quota")):
        mark_exhausted(model)
        # A resolved model that just got exhausted should be re-picked next call.
        _drop_resolved(model)
    elif any(s in msg for s in ("404", "not_found", "not found", "unsupported", "is not found")):
        mark_unavailable(model)
        _drop_resolved(model)


def _drop_resolved(model: str):
    for tier, m in list(_resolved.items()):
        if m == model:
            _resolved.pop(tier, None)


def candidates(task_type: str = "browser_agent") -> list[str]:
    """Ordered models to try for a task, resolved-first, skipping cooled-down ones."""
    tier = TASK_TIER_MAP.get(task_type, ModelTier.LARGE)
    models = SMALL_MODELS if tier == ModelTier.SMALL else LARGE_MODELS
    ordered = ([_resolved[tier]] if tier in _resolved else []) + \
              [m for m in models if m != _resolved.get(tier)]
    live = [m for m in ordered if _available(m)]
    return live or models[:1]  # if everything is cooling down, best-effort try the primary


def get_model(task_type: str = "browser_agent") -> str:
    """Best available model for a task type — instant, no network probe."""
    return candidates(task_type)[0]


def get_model_for_tier(tier: ModelTier) -> str:
    """Best available model for a tier — instant, no network probe."""
    if tier in _resolved and _available(_resolved[tier]):
        return _resolved[tier]
    models = SMALL_MODELS if tier == ModelTier.SMALL else LARGE_MODELS
    for m in models:
        if _available(m):
            return m
    return models[0]


def invalidate(tier: ModelTier | None = None):
    """Clear cooldowns + resolved cache (e.g. after quota reset). Tier kept for compat."""
    if tier is not None:
        _resolved.pop(tier, None)
    else:
        _resolved.clear()
    _cooldown.clear()


# Backward-compatible alias used by resume_parser.py
def get_working_model() -> str:
    return get_model_for_tier(ModelTier.LARGE)


async def resolve_models() -> None:
    """
    One-time startup probe (both tiers in parallel) that validates the best working
    model per tier and caches it, so the request hot path never makes a network probe.
    Non-fatal: if it fails or the key is missing, hot-path calls fall back to the
    optimistic primary + reactive cooldown.
    """
    from backend.config import settings
    key = settings.google_api_key
    if not key:
        return

    async def probe_tier(tier: ModelTier, models: list[str]):
        async with httpx.AsyncClient(timeout=6) as client:
            for m in models:
                # OpenRouter models ("provider/model") aren't reachable via Google's
                # endpoint — never probe them (that would 404 → 1h cooldown and kill
                # the fallback). They stay reactive: used only once Gemini cools down.
                if "/" in m:
                    continue
                if not _available(m):
                    continue
                try:
                    r = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}",
                        json={"contents": [{"parts": [{"text": "hi"}]}]},
                    )
                    d = r.json()
                    if "candidates" in d:
                        _resolved[tier] = m
                        print(f"[ModelRouter] {tier.value.upper()} → {m}")
                        return
                    code = d.get("error", {}).get("code")
                    if code == 429:
                        mark_exhausted(m)  # exists but exhausted — keep looking for a fresh one
                    elif code == 404:
                        mark_unavailable(m)
                except Exception:
                    continue

    try:
        await asyncio.gather(
            probe_tier(ModelTier.SMALL, SMALL_MODELS),
            probe_tier(ModelTier.LARGE, LARGE_MODELS),
        )
    except Exception as e:
        print(f"[ModelRouter] resolve_models failed (using optimistic defaults): {e}")


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
