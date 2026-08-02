"""Token price table. Prices go stale — stamp version + date on every run."""

from __future__ import annotations

PRICE_TABLE_VERSION = "2026-09-01"
PRICE_TABLE_DATE = "2026-09-01"

# USD per 1M tokens: (input, output)
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    "mock": (0.0, 0.0),
    "replay": (0.0, 0.0),
}


def prices_for(model: str) -> tuple[float, float]:
    if model in PRICES:
        return PRICES[model]
    # Unknown model: treat as gpt-4o-mini so dry-run still produces a number.
    return PRICES["gpt-4o-mini"]


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = prices_for(model)
    return (input_tokens / 1_000_000.0) * inp + (output_tokens / 1_000_000.0) * out


def tokens_from_trace(trace) -> tuple[int, int, int]:
    inp = sum(step.model_input_tokens for step in trace.steps)
    out = sum(step.model_output_tokens for step in trace.steps)
    return inp, out, inp + out
