from aeh.tasks.registry import KNOWN_GRADER_TYPES, KNOWN_TOOLS

__all__ = [
    "KNOWN_GRADER_TYPES",
    "KNOWN_TOOLS",
    "load_suite",
    "load_task",
    "validate_suite",
]


def __getattr__(name: str):
    if name in {"load_suite", "load_task", "validate_suite"}:
        from aeh.tasks.loader import load_suite, load_task, validate_suite

        return {"load_suite": load_suite, "load_task": load_task, "validate_suite": validate_suite}[
            name
        ]
    raise AttributeError(name)
