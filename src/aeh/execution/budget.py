"""Independent ceilings: steps, tokens, wall-clock. First one to fire wins."""

from __future__ import annotations

import time

from aeh.errors import BudgetExceeded


class Budget:
    def __init__(self, max_steps: int, max_tokens: int, timeout_s: float) -> None:
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.timeout_s = float(timeout_s)
        self.steps_used = 0
        self.tokens_used = 0
        self.started_at = time.monotonic()

    def remaining_timeout(self) -> float:
        remaining = self.timeout_s - (time.monotonic() - self.started_at)
        return max(0.0, remaining)

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self.started_at) * 1000.0

    def consume_step(self) -> None:
        self.steps_used += 1
        reason = self.exceeded()
        if reason:
            raise BudgetExceeded(reason)

    def consume_tokens(self, count: int) -> None:
        self.tokens_used += count
        reason = self.exceeded()
        if reason:
            raise BudgetExceeded(reason)

    def exceeded(self) -> str | None:
        if self.remaining_timeout() <= 0:
            return "timeout"
        if self.steps_used > self.max_steps:
            return "max_steps"
        if self.steps_used == self.max_steps:
            # At the ceiling after completing the last allowed step, the next
            # consume_step will fire. Being *at* max_steps is still allowed.
            pass
        if self.tokens_used > self.max_tokens:
            return "budget"
        return None

    def would_exceed_step(self) -> bool:
        return self.steps_used >= self.max_steps

    def would_exceed_tokens(self, additional: int = 0) -> bool:
        return (self.tokens_used + additional) > self.max_tokens

    def check_or_raise(self) -> None:
        reason = self.exceeded()
        if reason:
            raise BudgetExceeded(reason)
