"""Judge: LLM 工具调用循环，用于内容分类。"""

import json
import logging
from typing import Any

from modules.memory.markdown_store import MarkdownStore
from modules.proactive.domain.models import DataItem, GatewayResult, JudgeResult

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = """你是一个主动内容评估器。你接收候选项目并决定是否通知用户。

工具:
- recall_memory(query): 搜索用户的长期记忆以获取相关偏好或过去的交互。
- get_content(item_id): 获取项目的完整内容。
- mark_interesting(item_id, reason): 将项目标记为值得通知用户。
- mark_not_interesting(item_id, reason): 将项目标记为不值得通知。
- message_push(text): 准备发送给用户的草稿消息。
- finish_turn(decision): 完成评估。decision 必须是 "reply" 或 "skip"。

规则:
- 根据用户偏好和最近上下文评估每个项目。
- recall_memory 每轮最多调用一次；得到结果后必须开始分类候选，不能重复查询同类偏好。
- 稳定用户画像和近期上下文只用于筛选、排序和判断打扰时机，不得据此编造候选内容之外的事实。
- 保持主动性：如果项目包含重要信息、紧急警报、安全警告或时间敏感更新，将其标记为有趣。
- 安全警报、紧急系统消息和关键更新应始终标记为有趣。
- 如果有任何有趣的项目，调用 message_push 然后 finish_turn("reply")。
- 如果没有有趣的项目，finish_turn("skip")。
- 生成的消息必须使用中文。
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
    """LLM 工具调用循环，用于主动内容评估。"""

    def __init__(
        self,
        llm_client,
        memory_engine=None,
        markdown_store: MarkdownStore | None = None,
        max_steps: int = 12,
    ) -> None:
        self._llm = llm_client
        self._memory = memory_engine
        self._markdown = markdown_store
        self._max_steps = max_steps

    async def evaluate(
        self,
        gateway: GatewayResult,
        chat_id: str = "",
        *,
        policy_topics: tuple[str, ...] = (),
    ) -> JudgeResult:
        """运行 judge 循环：LLM 通过工具分类内容。"""
        items = gateway.all_items
        if not items:
            return JudgeResult(decision="skip")

        # 候选条目保持精简，正文按需通过工具获取。
        item_list = "\n".join(
            f"- [{i}][{it.source}] {it.title}: {it.summary[:120]}"
            for i, it in enumerate(items)
        )
        logger.info(f"Judge evaluating {len(items)} items:\n{item_list}")
        
        messages = [
            {"role": "system", "content": _JUDGE_SYSTEM},
        ]
        memory_context = self._build_memory_context()
        if memory_context:
            messages.append({
                "role": "system",
                "content": (
                    "以下是主动与被动链路共享的用户记忆上下文。"
                    "仅用于判断兴趣、禁忌、规则和是否适合打扰：\n\n"
                    f"{memory_context}"
                ),
            })
        if policy_topics:
            messages.append({
                "role": "system",
                "content": (
                    "用户明确配置的主动关注主题如下；优先挑选与这些主题相关且有新增价值的内容："
                    + "、".join(policy_topics)
                ),
            })
        messages.append({
            "role": "user",
            "content": f"Evaluate these items:\n\n{item_list}",
        })

        interesting: list[str] = []
        discarded: list[str] = []
        draft_message = ""
        decision = ""
        finished = False
        recall_used = False

        for step in range(self._max_steps):
            logger.info(f"Judge step {step+1}/{self._max_steps}")
            current_tools = [
                schema
                for schema in TOOL_SCHEMAS
                if not (
                    recall_used
                    and schema.get("function", {}).get("name") == "recall_memory"
                )
            ]
            response = self._llm.generate(messages=messages, tools=current_tools)
            logger.info(f"Judge response: {response.content[:200]}, tool_calls: {len(response.tool_calls or [])}")

            if not response.tool_calls:
                # 如果没有工具调用但有有趣项目，强制调用 message_push
                if interesting and not draft_message:
                    logger.info("No tool calls but items marked interesting, forcing message_push")
                    # 使用第一个有趣项目的内容作为消息
                    first_interesting_idx = interesting[0]
                    if first_interesting_idx.isdigit() and int(first_interesting_idx) < len(items):
                        draft_message = items[int(first_interesting_idx)].content
                        decision = "reply"
                        break
                decision = "skip"
                break

            tool_results: list[tuple[Any, str]] = []
            requested_decision = ""
            for tc in response.tool_calls:
                logger.info(f"Tool call: {tc.name}, args: {tc.arguments}")
                if tc.name == "recall_memory":
                    if recall_used:
                        result_text = "本轮已经查询过记忆，请立即分类候选并完成评估。"
                    else:
                        recall_used = True
                        result_text = self._dispatch_tool(
                            tc,
                            items,
                            interesting,
                            discarded,
                            draft_message,
                        )
                else:
                    result_text = self._dispatch_tool(
                        tc,
                        items,
                        interesting,
                        discarded,
                        draft_message,
                    )
                tool_results.append((tc, result_text))
                if tc.name == "message_push":
                    args = tc.arguments if isinstance(tc.arguments, dict) else {}
                    draft_message = args.get("text", "")
                    logger.info(f"Draft message staged: {draft_message[:100]}...")
                elif tc.name == "finish_turn":
                    args = tc.arguments if isinstance(tc.arguments, dict) else {}
                    requested = args.get("decision", "skip")
                    if requested == "reply" and not draft_message:
                        tool_results[-1] = (
                            tc,
                            "不能在没有 message_push 草稿时完成 reply；"
                            "请先生成真实候选内容对应的消息。",
                        )
                    else:
                        requested_decision = requested

            messages.append({"role": "assistant", "content": response.content, "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments if isinstance(tc.arguments, dict) else {})}}
                for tc in response.tool_calls
            ]})
            for tc, result_text in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

            if requested_decision:
                decision = "reply" if draft_message else requested_decision
                finished = True
                logger.info(f"Judge decision: {decision}")

            if finished:
                break

        if not decision:
            if policy_topics and items:
                fallback_items = items[:3]
                interesting.extend(str(index) for index in range(len(fallback_items)))
                draft_message = _build_policy_fallback_message(fallback_items)
                decision = "reply"
                logger.warning(
                    "Judge 未完成工具协议，按明确兴趣主题生成保守兜底消息: topics=%s",
                    policy_topics,
                )
            else:
                decision = "reply" if draft_message else "skip"

        # 强制分类未分类的项目
        classified = set(interesting) | set(discarded)
        unclassified = [it for i, it in enumerate(items) if str(i) not in classified and it.item_id not in classified]
        for it in unclassified:
            discarded.append(it.item_id)

        cited = _resolve_item_ids(interesting, items)
        discarded_ids = _resolve_item_ids(discarded, items)

        logger.info(f"Judge final decision: {decision}, message: {draft_message[:100] if draft_message else 'none'}")
        
        return JudgeResult(
            decision=decision,
            message=draft_message,
            cited_item_ids=cited,
            discarded_ids=discarded_ids,
        )

    def _build_memory_context(self) -> str:
        """读取与被动链路相同的稳定档案和近期压缩上下文。"""
        if self._markdown is None:
            return ""
        try:
            return self._markdown.render_prompt_memory()
        except Exception:
            logger.exception("主动评估记忆上下文构建失败")
            return ""

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


def _resolve_item_ids(references: list[str], items: list[DataItem]) -> list[str]:
    """把模型使用的索引或真实标识统一转换为数据源条目标识。"""
    known_ids = {item.item_id for item in items}
    resolved: list[str] = []
    for reference in references:
        item_id = ""
        if reference in known_ids:
            item_id = reference
        elif reference.isdigit() and int(reference) < len(items):
            item_id = items[int(reference)].item_id
        if item_id and item_id not in resolved:
            resolved.append(item_id)
    return resolved


def _build_policy_fallback_message(items: list[DataItem]) -> str:
    """模型未完成协议时，用真实候选字段生成不编造的简短推送。"""

    lines = ["你可能会感兴趣的最新内容："]
    for index, item in enumerate(items, start=1):
        lines.append(f"\n{index}. {item.title}")
        summary = item.summary.strip()
        if summary:
            lines.append(summary[:240])
        url = next(
            (
                line.strip()
                for line in item.content.splitlines()
                if line.strip().startswith(("http://", "https://"))
            ),
            "",
        )
        if url:
            lines.append(url)
    return "\n".join(lines)
