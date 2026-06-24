"""Lightweight per-request performance instrumentation for TAIA."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("taia.perf")


class RequestTimer:
    """Accumulates stage timings and logs a single summary line per request."""

    def __init__(self, label: str = "chat") -> None:
        self.label = label
        self._t0 = time.perf_counter()
        self._last = self._t0
        self.stages: list[tuple[str, float]] = []

    def mark(self, stage: str) -> float:
        now = time.perf_counter()
        elapsed = now - self._last
        self.stages.append((stage, elapsed))
        self._last = now
        logger.info("[%.2fs] %s", elapsed, stage)
        return elapsed

    def finish(self) -> dict[str, Any]:
        total = time.perf_counter() - self._t0
        summary = " | ".join(f"[{s:.2f}s] {name}" for name, s in self.stages)
        logger.info("TAIA perf (%s): %s | Total: %.2fs", self.label, summary, total)
        return {"stages": [{"name": n, "seconds": round(s, 3)} for n, s in self.stages], "total_s": round(total, 3)}
