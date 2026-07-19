"""Loud failures. A silently skipped task is a corrupted measurement."""


class HarnessError(Exception):
    """Base class for harness bugs and configuration errors."""


class TaskLoadError(HarnessError):
    """A task file failed validation and must not be silently skipped."""


class ToolError(HarnessError):
    """A tool rejected the call or failed during execution."""


class SandboxEscapeError(ToolError):
    """A filesystem path resolved outside the sandbox root."""


class AllowlistError(ToolError):
    """An HTTP request targeted a host that is not on the fixture allowlist."""


class BudgetExceeded(HarnessError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
