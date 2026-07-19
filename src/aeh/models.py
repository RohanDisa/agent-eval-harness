"""Frozen core data models. Everything downstream depends on these being stable."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator

Category = Literal["retrieval", "multi_step", "tool_use", "refusal", "long_horizon"]
TerminatedBy = Literal["completed", "max_steps", "timeout", "budget", "error"]
FailureClass = Literal[
    "tool_error",
    "malformed_tool_call",
    "hallucinated_tool",
    "budget_exhausted",
    "wrong_answer",
    "no_answer",
    "refusal",
    "harness_error",
]

KNOWN_CATEGORIES = {
    "retrieval",
    "multi_step",
    "tool_use",
    "refusal",
    "long_horizon",
}


class TaskSetup(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    sql: str | None = None
    http_fixtures: list[str] = Field(default_factory=list)


class GraderSpec(BaseModel):
    type: str
    model_config = {"extra": "allow"}


class Task(BaseModel):
    model_config = {"populate_by_name": True}

    id: str
    suite: str
    prompt: str
    category: Category
    difficulty: int = Field(ge=1, le=5)
    tools: list[str]
    setup: TaskSetup | None = None
    outcome_graders: list[GraderSpec] = Field(
        default_factory=list,
        validation_alias=AliasChoices("graders", "outcome_graders"),
    )
    invariants: list[str] = Field(default_factory=list)
    golden_trace_id: str | None = None
    max_steps: int = 15
    max_tokens: int = 30_000
    timeout_s: int = 120
    tags: list[str] = Field(default_factory=list)

    @property
    def graders(self) -> list[GraderSpec]:
        return self.outcome_graders

    @field_validator("id")
    @classmethod
    def _slug_id(cls, value: str) -> str:
        if not value or any(ch.isspace() for ch in value):
            raise ValueError("task id must be a non-empty slug without whitespace")
        return value


class ToolCall(BaseModel):
    index: int
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None
    error: str | None = None
    latency_ms: float = 0.0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    malformed: bool = False
    hallucinated: bool = False
    span_id: str = ""
    parent_span_id: str | None = None
    injected_fault: str | None = None


class Step(BaseModel):
    index: int
    model_input_tokens: int = 0
    model_output_tokens: int = 0
    model_latency_ms: float = 0.0
    reasoning_text: str | None = None
    tool_call: ToolCall | None = None
    raw_response: dict[str, Any] = Field(default_factory=dict)
    span_id: str = ""
    parent_span_id: str | None = None


class SpanNode(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    kind: str
    name: str
    index: int
    latency_ms: float = 0.0
    tokens: int = 0
    children: list[SpanNode] = Field(default_factory=list)


class Trace(BaseModel):
    run_id: str
    task_id: str
    attempt: int
    seed: int
    adapter: str
    model: str
    steps: list[Step] = Field(default_factory=list)
    final_output: str | None = None
    terminated_by: TerminatedBy
    wall_clock_ms: float
    sandbox_final_state: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    task_category: str = ""
    span_tree: list[dict[str, Any]] = Field(default_factory=list)

    def build_span_tree(self) -> list[dict[str, Any]]:
        nodes: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for step in self.steps:
            sid = step.span_id or f"step-{step.index}"
            nodes[sid] = {
                "span_id": sid,
                "parent_span_id": step.parent_span_id,
                "kind": "step",
                "name": f"step-{step.index}",
                "index": step.index,
                "latency_ms": step.model_latency_ms,
                "tokens": step.model_input_tokens + step.model_output_tokens,
                "children": [],
            }
            order.append(sid)
            if step.tool_call:
                tc = step.tool_call
                tid = tc.span_id or f"tool-{step.index}"
                nodes[tid] = {
                    "span_id": tid,
                    "parent_span_id": tc.parent_span_id or sid,
                    "kind": "tool",
                    "name": tc.name,
                    "index": tc.index,
                    "latency_ms": tc.latency_ms,
                    "tokens": 0,
                    "injected_fault": tc.injected_fault,
                    "children": [],
                }
                order.append(tid)
        roots: list[dict[str, Any]] = []
        for sid in order:
            node = nodes[sid]
            parent = node.get("parent_span_id")
            if parent and parent in nodes:
                nodes[parent]["children"].append(node)
            else:
                roots.append(node)
        self.span_tree = roots
        return roots

    def ensure_spans(self) -> list[dict[str, Any]]:
        """Fill missing span ids so v1 traces still form a tree, then assemble it."""
        for step in self.steps:
            if not step.span_id:
                step.span_id = f"step-{step.index}"
            if step.tool_call:
                if not step.tool_call.span_id:
                    step.tool_call.span_id = f"tool-{step.index}"
                if not step.tool_call.parent_span_id:
                    step.tool_call.parent_span_id = step.span_id
        return self.build_span_tree()


class GradeResult(BaseModel):
    grader: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    detail: str
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    errored: bool = False
    tier: int = 0


class RunResult(BaseModel):
    trace: Trace
    grades: list[GradeResult] = Field(default_factory=list)
    success: bool
    failure_class: FailureClass | None = None
    cost_usd: float = 0.0
    total_tokens: int = 0
    needs_human_review: bool = False


class SuiteResult(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime
    config: dict[str, Any] = Field(default_factory=dict)
    results: list[RunResult] = Field(default_factory=list)


class ToolResult(BaseModel):
    ok: bool
    output: str = ""
    error: str | None = None
