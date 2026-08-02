"""Canonical names the loader validates against. Unknown names fail loudly."""

KNOWN_TOOLS = {
    "fs_read",
    "fs_write",
    "fs_list",
    "http_get",
    "calculator",
    "sql",
    "broken_tool",
}

KNOWN_GRADER_TYPES = {
    "exact",
    "contains",
    "not_contains",
    "numeric_close",
    "json_schema",
    "file_state",
    "sql_result",
    "step_budget",
    "tool_sequence",
    "judge",
}
