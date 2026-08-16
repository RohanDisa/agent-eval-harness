"""Redact PII and secrets on write, before persist."""

from __future__ import annotations

import re
from typing import Any

from aeh.models import Trace

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
DEFAULT_PATTERNS = (
    (EMAIL, "[redacted-email]"),
    (CARD, "[redacted-card]"),
    (re.compile(r"\bhunter2\b", re.I), "[redacted-secret]"),
    (re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*\S+"), r"\1=[redacted]"),
)


def redact_text(text: str, extra_patterns: list[tuple[re.Pattern[str], str]] | None = None) -> str:
    out = text
    for pat, repl in DEFAULT_PATTERNS + tuple(extra_patterns or ()):
        out = pat.sub(repl, out)
    return out


def _redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: _redact_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_obj(v) for v in value]
    return value


def redact_trace(trace: Trace) -> Trace:
    copy = trace.model_copy(deep=True)
    if copy.final_output:
        copy.final_output = redact_text(copy.final_output)
    if copy.error:
        copy.error = redact_text(copy.error)
    for step in copy.steps:
        if step.reasoning_text:
            step.reasoning_text = redact_text(step.reasoning_text)
        step.raw_response = _redact_obj(step.raw_response)
        if step.tool_call:
            step.tool_call.arguments = _redact_obj(step.tool_call.arguments)
            if step.tool_call.result:
                step.tool_call.result = redact_text(step.tool_call.result)
            if step.tool_call.error:
                step.tool_call.error = redact_text(step.tool_call.error)
    return copy
