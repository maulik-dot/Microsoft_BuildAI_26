"""
Planning & Task Decomposition — Gap #5
Tracks which plan steps are done/pending/failed and supports dynamic re-planning.
"""

import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Step:
    id: int
    description: str
    status: Literal["pending", "running", "done", "failed"] = "pending"
    failure_reason: str = ""


class StepTracker:
    def __init__(self, steps: list[str]):
        self.steps = [Step(id=i + 1, description=s) for i, s in enumerate(steps)]

    def mark_running(self, idx: int):
        if 0 <= idx < len(self.steps):
            self.steps[idx].status = "running"

    def mark_done(self, idx: int):
        if 0 <= idx < len(self.steps):
            self.steps[idx].status = "done"

    def mark_failed(self, idx: int, reason: str = ""):
        if 0 <= idx < len(self.steps):
            self.steps[idx].status = "failed"
            self.steps[idx].failure_reason = reason

    def get_pending(self) -> list[Step]:
        return [s for s in self.steps if s.status == "pending"]

    def get_failed(self) -> list[Step]:
        return [s for s in self.steps if s.status == "failed"]

    def all_done(self) -> bool:
        return all(s.status == "done" for s in self.steps)

    def to_prompt_block(self) -> str:
        lines = ["## TASK PROGRESS"]
        for s in self.steps:
            icon = {"pending": "⏳", "running": "▶️", "done": "✅", "failed": "❌"}.get(s.status, "•")
            line = f"{icon} Step {s.id}: {s.description}"
            if s.failure_reason:
                line += f" (FAILED: {s.failure_reason})"
            lines.append(line)
        pending = self.get_pending()
        if pending:
            lines.append(f"\n▶️ FOCUS ON: {pending[0].description}")
        return "\n".join(lines) + "\n"


class TaskScratchpad:
    """Cross-service data store for a single task run."""

    def __init__(self):
        self._data: dict[str, str] = {}

    def set(self, key: str, value: str):
        self._data[key] = value

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def dump(self) -> str:
        if not self._data:
            return ""
        lines = ["## SCRATCHPAD (data collected so far)"]
        for k, v in self._data.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines) + "\n"

    def is_empty(self) -> bool:
        return len(self._data) == 0


def parse_plan_steps(plan_text: str) -> list[str]:
    """Extract numbered steps from a plan string."""
    steps = re.findall(r'^\s*\d+[\.\)]\s*(.+)', plan_text, re.MULTILINE)
    return [s.strip() for s in steps if s.strip()]
