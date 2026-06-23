"""Judge: LLM tool-call loop for content classification (spec 4)."""

import json
import logging

from flow_agent.proactive.models import DataItem, GatewayResult, JudgeResult

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = """You are a proactive content evaluator. You receive candidate items and decide whether to notify the user.

Tools:
- recall_memory(query): Search user's long-term memory for relevant preferences or past interactions.
- get_content(item_id): Retrieve the full content body for an item.
- mark_interesting(item_id, reason): Mark an item as worth notifying the user about.
- mark_not_interesting(item_id, reason): Mark an item as not worth notifying.
- message_push(text): Stage a draft message to send to the user.
- finish_turn(decision): Complete evaluation. decision must be "reply" or "skip".

Rules:
- Evaluate each item against user preferences and recent context.
- Only mark interesting if the user would genuinely care.
- If any items are interesting, call message_push then finish_turn("reply").
- If nothing is interesting, finish_turn("skip").
"""

TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "recall_memory", "description": "Query user memory", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_content", "description": "Get full content of an item", "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}}, "required": ["item_id"]}}},
    {"type": "function", "function": {"name": "mark_interesting", "description": "Mark an item as interesting", "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["item_id", "reason"]}}},
    {"type": "function", "function": {"name": "mark_not_interesting", "description": "Mark an item as not interesting", "parameters": {"type": "object", "properties": {"item_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["item_id", "reason"]}}},
    {"type": "function", "function": {"name": "message_push", "description": "Stage a draft message", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "finish_turn", "description": "Complete evaluation", "parameters": {"type": "object", "properties": {"decision": {"type": "string", "enum": ["reply", "skip"]}}, "required": ["decision"]}}},
]


class JudgeLoop:
    """LLM tool-call loop for proactive content evaluation (spec 4a-4e)."""

    def __init__(self, llm_client, memory_engine=None, max_steps: int = 12) -> None:
        self._llm = llm_client
        self._memory = memory_engine
        self._max_steps = max_steps

    async def evaluate(self, gateway: GatewayResult, chat_id: str = "") -> JudgeResult:
        """Run the judge loop: LLM classifies content via tools (spec 4b-4e)."""
        items = gateway.all_items
        if not items:
            return JudgeResult(decision="skip")

        # Build context
        item_list = "\n".join(
            f"- [{i}][{it.source}] {it.title}: {it.summary[:120]}"
            for i, it in enumerate(items)
        )
        messages = [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": f"Evaluate these items:\n\n{item_list}"},
        ]

        interesting: list[str] = []
        discarded: list[str] = []
        draft_message = ""
        decision = "skip"

        for step in range(self._max_steps):
            response = self._llm.generate(messages=messages, tools=TOOL_SCHEMAS)

            if not response.tool_calls:
                decision = "skip"
                break

            for tc in response.tool_calls:
                result_text = self._dispatch_tool(tc, items, interesting, discarded, draft_message)
                if tc.name == "message_push":
                    args = tc.arguments if isinstance(tc.arguments, dict) else {}
                    draft_message = args.get("text", "")
                elif tc.name == "finish_turn":
                    args = tc.arguments if isinstance(tc.arguments, dict) else {}
                    decision = args.get("decision", "skip")
                    break

            messages.append({"role": "assistant", "content": response.content, "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments if isinstance(tc.arguments, dict) else {})}}
                for tc in response.tool_calls
            ]})
            for tc in response.tool_calls:
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(tc.name)})

            if decision in ("reply", "skip"):
                break

        # spec 4c: force classify unclassified items
        classified = set(interesting) | set(discarded)
        unclassified = [it for i, it in enumerate(items) if str(i) not in classified and it.item_id not in classified]
        for it in unclassified:
            discarded.append(it.item_id)

        cited = [items[int(i)].item_id for i in interesting if i.isdigit() and int(i) < len(items)]

        return JudgeResult(
            decision=decision,
            message=draft_message,
            cited_item_ids=cited,
            discarded_ids=discarded,
        )

    def _dispatch_tool(self, tc, items, interesting, discarded, draft) -> str:
        args = tc.arguments if isinstance(tc.arguments, dict) else {}
        if tc.name == "recall_memory":
            return self._memory.retrieve_for_prompt(args.get("query", "")) if self._memory else ""
        elif tc.name == "get_content":
            iid = args.get("item_id", "")
            for i, it in enumerate(items):
                if it.item_id == iid or str(i) == iid:
                    return it.content[:2000]
            return ""
        elif tc.name == "mark_interesting":
            interesting.append(args.get("item_id", ""))
            return "marked"
        elif tc.name == "mark_not_interesting":
            discarded.append(args.get("item_id", ""))
            return "marked"
        elif tc.name == "message_push":
            return "staged"
        elif tc.name == "finish_turn":
            return "done"
        return ""
