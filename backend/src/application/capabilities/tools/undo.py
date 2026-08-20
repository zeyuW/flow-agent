"""/undo tool: delete the last passive turn and rollback consolidated cursor (spec 5).

Provides the undo capability as a tool callable by the agent or system.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from application.capabilities.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class UndoTool:
    """Undo tool: delete last conversation turn and cleanup memory.

    This tool is callable by the system to rollback the last user+assistant turn.
    It handles message deletion, cursor rollback, and marks related memories as superseded.
    """

    session_manager = None  # Set during bootstrap
    memory_store = None  # Optional: MemoryStore for memory cleanup (spec 5e)

    @property
    def name(self) -> str:
        return "undo"

    @property
    def description(self) -> str:
        return (
            "Undo the last conversation turn. Deletes the last user message "
            "and corresponding assistant response, rolls back the consolidation "
            "cursor, and marks related memories as superseded."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_key": {
                    "type": "string",
                    "description": "Session key to undo (default: 'default')",
                    "default": "default",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, only report what would be deleted",
                    "default": False,
                },
            },
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        try:
            import asyncio

            session_key = tool_input.get("session_key", "default")
            dry_run = tool_input.get("dry_run", False) in (True, "true", "True")

            if self.session_manager is None:
                return ToolResult(
                    ok=False, content="undo tool not configured (no session manager)"
                )

            session = self.session_manager.get_or_create(session_key)
            result = self.session_manager.find_last_passive_turn(session)

            if result is None:
                return ToolResult(ok=True, content="no passive turn found to undo")

            ids_to_delete, start_idx, end_idx = result

            if dry_run:
                return ToolResult(
                    ok=True,
                    content=json.dumps(
                        {
                            "dry_run": True,
                            "messages_to_delete": len(ids_to_delete),
                            "ids": ids_to_delete,
                            "start_index": start_idx,
                            "end_index": end_idx,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

            # Execute undo
            deleted = asyncio.run(self.session_manager.undo_last_turn(session))

            # spec 5e: Mark related memories as superseded
            memory_cleanup = 0
            if self.memory_store is not None:
                try:
                    for mid in ids_to_delete:
                        related = self.memory_store.search_by_source_ref(
                            f"message:{session_key}:{mid}"
                        )
                        if related:
                            mem_ids = [m.id for m in related]
                            self.memory_store.mark_superseded_batch(mem_ids)
                            memory_cleanup += len(mem_ids)
                except Exception:
                    logger.exception("memory cleanup during undo failed")

            return ToolResult(
                ok=True,
                content=json.dumps(
                    {
                        "deleted_messages": deleted,
                        "cursor_rolled_back": session.last_consolidated,
                        "memories_superseded": memory_cleanup,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except Exception as exc:
            logger.exception("undo failed")
            return ToolResult(ok=False, content=f"undo failed: {exc}")
