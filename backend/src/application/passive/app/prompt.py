"""被动回合的 PromptRender 用例。"""

from __future__ import annotations

import logging
from datetime import datetime

from application.agent.app.agent import Agent
from application.capabilities.tools.registry import ToolRegistry
from application.memory.ports import MemoryPromptStore, MemoryQueryService
from application.passive.app.phase import TurnFlow

logger = logging.getLogger(__name__)


class PromptRenderer:
    """构建被动回合的角色、记忆、历史和工具提示。"""

    def __init__(
        self,
        *,
        agent: Agent,
        tool_registry: ToolRegistry,
        memory_engine: MemoryQueryService | None = None,
        markdown_store: MemoryPromptStore | None = None,
        retrieval_max_items: int = 6,
        tool_selection_max: int = 8,
    ) -> None:
        self.agent = agent
        self.tool_registry = tool_registry
        self.memory_engine = memory_engine
        self.markdown_store = markdown_store
        self.retrieval_max_items = retrieval_max_items
        self.tool_selection_max = max(1, tool_selection_max)

    def render(self, flow: TurnFlow) -> TurnFlow:
        """为当前回合生成最终模型消息。"""

        persona_block = self._build_persona_block(
            proactive=False,
            channel=flow.channel,
        )
        memory_block = self.build_memory_block(flow.session_id, flow.user_input)

        flow.tools = self.tool_registry.select_openai_tools(
            flow.user_input,
            max_tools=self.tool_selection_max,
        )
        scheduled_execution = bool(flow.inbound_metadata.get("scheduled_task"))
        if scheduled_execution:
            blocked = {
                "schedule_task",
                "list_scheduled_tasks",
                "cancel_scheduled_task",
            }
            flow.tools = [
                item
                for item in flow.tools
                if item.get("function", {}).get("name") not in blocked
            ]

        names = [t.get("function", {}).get("name", "") for t in flow.tools]
        instructions = [
            f"当前系统时间: {datetime.now().astimezone().isoformat()}",
            f"可用工具: {chr(10).join(names) if names else '无'}",
            "当需要获取外部信息时，请使用工具函数调用。",
            "用户要求读取文件、写入文件、编辑文本或执行命令时，必须分别调用 read、write、edit、bash；"
            "只要可用工具中列出对应名称，就不得声称没有该能力。",
            "用户要求安装 Skill 时，必须调用 install_skill；不得使用 npx skills，"
            "也不得写入 ~/.agents、~/.claude 或其他 Agent 的目录。"
            "Flow 的个人 Skill 唯一安装位置是 ~/.flow/skills。",
        ]
        if scheduled_execution:
            instructions.append(
                "当前消息是已经到期的定时任务，立即执行任务并报告结果，"
                "不要再次创建或修改定时任务。"
            )
        else:
            instructions.append(
                "当用户要求提醒、定时执行或周期任务时，必须调用 schedule_task，"
                "不得仅写入长期记忆，也不得声称系统无法定时唤醒。"
            )
            instructions.append(
                "当用户要求长时间不互动后主动联系、主动推送感兴趣内容或修改主动策略时，"
                "必须调用 configure_proactive_policy；未给出具体时长时默认使用 120 分钟并告知用户。"
                "查询当前策略时调用 get_proactive_status。"
            )
            instructions.append(
                "当用户要求执行插件提供的后台任务时，先调用 list_automation_jobs 确认名称，"
                "再调用 run_automation_job；需要查看进度或结果时调用 list_automation_runs。"
                "后台任务不是 MCP 服务，不得使用 mcp_list 判断后台任务是否存在。"
                "回答时必须原样引用工具返回的 job_name，不得自行改写任务名称。"
            )

        flow.messages = self.agent.build_turn_messages(
            user_input=flow.user_input,
            persona_block=persona_block,
            memory_block=memory_block,
            retrieval_block="",
            tool_instructions="\n\n".join(instructions),
            session_id=flow.session_id,
            media=list(flow.inbound_metadata.get("media") or []),
        )
        return flow

    def _build_persona_block(self, proactive: bool, channel: str) -> str:
        if self.agent.persona_resolver is not None:
            return self.agent.persona_resolver.render_block(
                channel=channel,
                proactive_mode=proactive,
            )
        return ""

    def build_memory_block(self, session_id: str, user_input: str = "") -> str:
        """构建由长期记忆和近期对话组成的提示词记忆块。"""

        blocks: list[str] = []

        if self.markdown_store is not None:
            try:
                markdown_block = self.markdown_store.render_prompt_memory()
                if markdown_block:
                    blocks.append(markdown_block)
            except Exception:
                logger.exception("Markdown 记忆提示词构建失败")

        if self.memory_engine is not None and user_input.strip():
            try:
                long_term_block = self.memory_engine.retrieve_for_prompt(
                    user_input,
                    max_items=self.retrieval_max_items,
                )
                if long_term_block:
                    blocks.append(long_term_block)
            except Exception:
                logger.exception("长期记忆检索失败")

        history = self.agent.context.get_history(session_id)
        if history:
            lines = ["## 近期对话回顾"]
            for msg in history[-6:]:
                role = msg.get("role", "unknown")
                content = str(msg.get("content", ""))[:200]
                label = "用户" if role == "user" else "助手"
                lines.append(f"- {label}: {content}")
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)
