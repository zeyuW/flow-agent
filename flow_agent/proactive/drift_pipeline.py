"""漂移执行管道：扫描 → 准备 → 执行 → 持久化。"""

import json
import logging

from flow_agent.proactive.drift_models import DriftSkill, DriftRun, DriftTick
from flow_agent.proactive.drift_store import DriftStateStore
from flow_agent.proactive.drift_tools import (
    get_drift_tool_schemas,
    get_post_push_tool_schemas,
    dispatch_drift_tool,
)

logger = logging.getLogger(__name__)

_DRIFT_SYSTEM_PROMPT = """你是一个漂移模式执行器。当没有外部推送内容时，你可以利用空闲时间执行用户定义的技能。

规则：
1. 浏览可用的技能列表，选择一个执行
2. 使用 read_file 读取相关文件，使用 write_file 写文件
3. 如果需要通知用户，使用 message_push。调用后只能使用 write_file 和 finish_drift 收尾
4. 完成后调用 finish_drift，提供本次运行的摘要和建议的下一步"""


class DriftTurnPipeline:
    """漂移模式四阶段执行管道：扫描 → 准备 → 执行 → 持久化。"""

    def __init__(
        self,
        *,
        state_store: DriftStateStore,
        llm_client=None,
        memory_engine=None,
        mcp_pool=None,
        max_steps: int = 10,
        workspace: str = "",
    ) -> None:
        self._store = state_store
        self._llm = llm_client
        self._memory = memory_engine
        self._mcp_pool = mcp_pool
        self._max_steps = max_steps
        self._workspace = workspace

    async def run(self, connected_mcp: set[str]) -> DriftTick:
        """执行一次漂移：扫描 → 准备 → 执行 → 持久化。"""
        tick = DriftTick()

        # 阶段 1: 扫描
        all_skills = self._store.scan_skills()
        tick.skills = self._store.filter_by_mcp(all_skills, connected_mcp)
        if not tick.skills:
            logger.debug("无可用漂移技能")
            return tick

        # 阶段 2: 准备
        messages = self._build_messages(tick.skills)
        tools = get_drift_tool_schemas()

        # 阶段 3: 执行
        ctx = {
            "message": "",
            "pushed": False,
            "skills": tick.skills,
            "runs": tick.runs,
            "workspace": self._workspace,
            "finished": False,
        }

        try:
            for _ in range(self._max_steps):
                if ctx["finished"]:
                    break

                # 选择工具集：message_push 后受限
                current_tools = get_post_push_tool_schemas() if ctx["pushed"] else tools

                response = self._llm.generate(messages=messages, tools=current_tools)
                if not response.tool_calls:
                    break
                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(
                                    tc.arguments if isinstance(tc.arguments, dict) else {},
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        for tc in response.tool_calls
                    ],
                })

                for tc in response.tool_calls:
                    args = tc.arguments if isinstance(tc.arguments, dict) else {}
                    result = dispatch_drift_tool(tc.name, args, ctx)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

                if ctx["finished"]:
                    break
        except Exception as exc:
            logger.exception("漂移技能执行失败")
            tick.runs.append(DriftRun(
                action="漂移执行异常",
                result="失败",
                status="failed",
                error=str(exc),
            ))

        # 提取暂存消息
        tick.message = ctx.get("message", "")

        if not ctx["finished"] and not any(
            run.status == "failed" for run in tick.runs
        ):
            tick.runs.append(DriftRun(
                action="漂移执行未完成工具协议",
                result="未完成",
                status="incomplete",
            ))

        # 阶段 4: 持久化
        self._store.append_run(tick)
        for skill in tick.skills:
            self._store.save_skill_state(skill)

        tick.finished = bool(ctx["finished"])
        return tick

    def _build_messages(self, skills: list[DriftSkill]) -> list[dict]:
        """构建初始消息：系统提示词 + 技能列表 + 运行历史。"""
        skill_desc = "\n\n".join(
            f"## {s.name}\n{s.description}"
            + (f"\n需要 MCP: {', '.join(s.requires_mcp)}" if s.requires_mcp else "")
            + (f"\n技能目录: {s.path}" if s.path else "")
            + (f"\n执行说明:\n{s.instructions[:4000]}" if s.instructions else "")
            + (f"\n连续状态: {json.dumps(s.state, ensure_ascii=False)}" if s.state else "")
            for s in skills
        )
        history = self._store.load_history(limit=5)
        hist_text = "\n".join(
            f"- [{r.timestamp}] {r.skill_name}: {r.action}" for r in history[-5:]
        ) if history else "无历史记录"

        messages = [
            {"role": "system", "content": _DRIFT_SYSTEM_PROMPT},
            {"role": "user", "content": f"可用技能:\n{skill_desc}\n\n最近运行历史:\n{hist_text}\n\n请选择一个技能并开始执行。"},
        ]
        return messages

    def close(self) -> None:
        """关闭漂移状态存储。"""

        self._store.close()
