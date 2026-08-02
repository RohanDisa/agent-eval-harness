"""Fault injection wrapper. Real outages are correlated; uniform random is the weaker model."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Mapping
from typing import Any, Literal

ErrorKind = Literal["timeout", "500", "garbage"]


class FaultController:
    def __init__(
        self,
        profile: Mapping[str, Any] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.profile = dict(profile or {})
        self.rng = rng or random.Random()
        self._burst_left: dict[str, int] = {}

    def decide(self, tool_name: str) -> str | None:
        spec = self.profile.get(tool_name) or {}
        kind = spec.get("error_kind") or "500"
        if spec.get("burst"):
            window = int(spec.get("burst_window") or spec.get("burst") or 0)
            if tool_name not in self._burst_left:
                if self.rng.random() < float(spec.get("fail_rate", 1.0)):
                    self._burst_left[tool_name] = max(1, window)
                else:
                    self._burst_left[tool_name] = 0
            if self._burst_left.get(tool_name, 0) > 0:
                self._burst_left[tool_name] -= 1
                return str(kind)
            return None
        fail_rate = float(spec.get("fail_rate", 0) or 0)
        if fail_rate and self.rng.random() < fail_rate:
            return str(kind)
        return None

    def extra_latency_ms(self, tool_name: str) -> float:
        spec = self.profile.get(tool_name) or {}
        return float(spec.get("latency_ms", 0) or 0)

    def apply_kind(self, kind: str, tool_name: str) -> tuple[str, str | None]:
        """Return (error_message, garbage_result). garbage_result set for garbage kind."""
        if kind == "timeout":
            return f"injected fault timeout for '{tool_name}'", None
        if kind == "garbage":
            return "", f"GARBAGE_PAYLOAD:{tool_name}"
        return f"injected fault 500 for '{tool_name}'", None


async def maybe_delay(controller: FaultController, tool_name: str) -> None:
    extra = controller.extra_latency_ms(tool_name)
    if extra:
        await asyncio.sleep(extra / 1000.0)
