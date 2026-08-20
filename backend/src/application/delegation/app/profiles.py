"""Subagent profile configs with tool set builders (spec 6)."""

from dataclasses import dataclass
from typing import Any

from application.delegation.app.models import SubagentSpec
from application.capabilities.tools.read import ReadTool
from infra.workspace import WORKSPACE_LAYOUT

PROFILE_RESEARCH = "research"
PROFILE_SCRIPTING = "scripting"
PROFILE_GENERAL = "general"


def build_spawn_spec(
    *,
    profile: str = PROFILE_RESEARCH,
    system_prompt: str = "",
    max_iterations: int = 30,
) -> SubagentSpec:
    """Build a SubagentSpec for the given profile (spec 3e, 6d)."""
    if profile == PROFILE_RESEARCH:
        return _build_research_spec(system_prompt, max_iterations)
    elif profile == PROFILE_SCRIPTING:
        return _build_scripting_spec(system_prompt, max_iterations)
    else:
        return _build_general_spec(system_prompt, max_iterations)


def _build_research_spec(prompt: str, max_iter: int) -> SubagentSpec:
    """Research profile: read-only tools — search, read files, no exec (spec 6b)."""
    tools = [
        ReadTool(WORKSPACE_LAYOUT.root, WORKSPACE_LAYOUT.flow_dir),
    ]
    return SubagentSpec(
        tools=tools,
        tool_schemas=[_tool_schema(t) for t in tools],
        system_prompt=prompt
        or "You are a research assistant. You can read files and search. Do not modify files or execute commands.",
        max_iterations=max_iter,
    )


def _build_scripting_spec(prompt: str, max_iter: int) -> SubagentSpec:
    """Scripting profile: file read/write, shell (no network) (spec 6c)."""
    tools = [
        ReadTool(WORKSPACE_LAYOUT.root, WORKSPACE_LAYOUT.flow_dir),
    ]
    return SubagentSpec(
        tools=tools,
        tool_schemas=[_tool_schema(t) for t in tools],
        system_prompt=prompt
        or "You are a coding assistant. You can read and write files and run shell commands.",
        max_iterations=max_iter,
    )


def _build_general_spec(prompt: str, max_iter: int) -> SubagentSpec:
    """General profile: full access (spec 6d fallback)."""
    tools = [
        ReadTool(WORKSPACE_LAYOUT.root, WORKSPACE_LAYOUT.flow_dir),
    ]
    return SubagentSpec(
        tools=tools,
        tool_schemas=[_tool_schema(t) for t in tools],
        system_prompt=prompt or "You are a general assistant with full tools.",
        max_iterations=max_iter,
    )


def _tool_schema(tool) -> dict:
    """Extract OpenAI function schema from a tool."""
    name = getattr(tool, "name", "unknown")
    desc = getattr(tool, "description", "")
    schema = getattr(tool, "input_schema", {})
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": schema,
        },
    }
