"""智能记忆检索的查询重写器。"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RewriteStatus(str, Enum):
    SUCCESS = "success"
    DEGRADED = "degraded"


@dataclass(slots=True)
class QueryRewriteResult:
    """查询重写结果（向后兼容）。"""
    rewritten_query: str
    intent: str
    hints: list[str]


@dataclass
class GateDecision:
    needs_episodic: bool
    episodic_query: str
    latency_ms: int
    procedure_query: str = ""
    history_status: RewriteStatus = RewriteStatus.SUCCESS
    procedure_status: RewriteStatus = RewriteStatus.SUCCESS
    history_reason: str = ""
    procedure_reason: str = ""

    @property
    def status(self) -> RewriteStatus:
        return (
            RewriteStatus.DEGRADED
            if RewriteStatus.DEGRADED in {self.history_status, self.procedure_status}
            else RewriteStatus.SUCCESS
        )


class QueryRewriter:
    """查询重写器，使用 LLM 提高检索准确性。

    分离情节性查询和程序性查询。
    """

    def __init__(
        self,
        llm_client: Any = None,
        *,
        model: str = "",
        max_tokens: int = 220,
        timeout_ms: int = 800,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._max_tokens = max(64, int(max_tokens))
        self._timeout_s = max(0.1, float(timeout_ms) / 1000.0)
        self._use_llm = llm_client is not None
        self._token_re = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

    def rewrite(self, query: str) -> QueryRewriteResult:
        """向后兼容的简单查询重写方法。"""
        text = (query or "").strip()
        if not text:
            return QueryRewriteResult(rewritten_query="", intent="empty", hints=[])
        hints: list[str] = []
        lowered = text.lower()
        if "叫什么" in text or "name" in lowered:
            hints.append("identity")
        if "喜欢" in text or "prefer" in lowered:
            hints.append("preference")
        if "计划" in text or "goal" in lowered:
            hints.append("goal")
        tokens = self._token_re.findall(text)
        rewritten = " ".join(tokens[:12])
        intent = hints[0] if hints else "general"
        if len(tokens) <= 1 and len(text) > 6:
            # Tokenization can occasionally fail on punctuation-heavy prompts.
            rewritten = text
            hints.append("fallback_raw_query")
        return QueryRewriteResult(rewritten_query=rewritten, intent=intent, hints=hints)

    async def decide(self, user_msg: str, recent_history: str) -> GateDecision:
        """决定查询重写策略（需要 LLM）。"""
        if not self._use_llm:
            # 回退到简单重写
            result = self.rewrite(user_msg)
            return GateDecision(
                needs_episodic=bool(result.rewritten_query),
                episodic_query=result.rewritten_query,
                latency_ms=0,
                procedure_query="",
                history_status=RewriteStatus.DEGRADED,
                history_reason="no_llm_client",
            )

        started = time.perf_counter()

        # 并行执行主重写和可选的程序性查询重写
        raw_output: str | None = None
        procedure_query = ""
        main_task = asyncio.create_task(
            self._call_llm(
                self._build_prompt(
                    user_msg=user_msg,
                    recent_history=recent_history,
                )
            )
        )
        procedure_task = asyncio.create_task(self._rewrite_procedure_query(user_msg))
        tasks = {main_task, procedure_task}
        try:
            done, pending = await asyncio.wait(tasks, timeout=self._timeout_s)
            for task in pending:
                _ = task.cancel()
            if pending:
                _ = await asyncio.gather(*pending, return_exceptions=True)
            if not done:
                return self._build_decision(
                    started=started,
                    needs_episodic=True,
                    episodic_query=user_msg,
                    history_status=RewriteStatus.DEGRADED,
                    history_reason="timeout",
                )

            if main_task in done:
                raw_output = await main_task
                episodic_query = self._parse_episodic_query(raw_output)
            else:
                episodic_query = user_msg

            if procedure_task in done:
                procedure_query = await procedure_task
            else:
                procedure_query = ""

            needs_episodic = bool(episodic_query.strip())
            return self._build_decision(
                started=started,
                needs_episodic=needs_episodic,
                episodic_query=episodic_query,
                procedure_query=procedure_query,
            )

        except Exception as exc:
            logger.exception("query rewrite failed: %s", exc)
            return self._build_decision(
                started=started,
                needs_episodic=True,
                episodic_query=user_msg,
                history_status=RewriteStatus.DEGRADED,
                history_reason=str(exc),
            )

    def _build_decision(
        self,
        started: float,
        needs_episodic: bool,
        episodic_query: str,
        procedure_query: str = "",
        history_status: RewriteStatus = RewriteStatus.SUCCESS,
        history_reason: str = "",
        procedure_status: RewriteStatus = RewriteStatus.SUCCESS,
        procedure_reason: str = "",
    ) -> GateDecision:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return GateDecision(
            needs_episodic=needs_episodic,
            episodic_query=episodic_query,
            latency_ms=latency_ms,
            procedure_query=procedure_query,
            history_status=history_status,
            history_reason=history_reason,
            procedure_status=procedure_status,
            procedure_reason=procedure_reason,
        )

    def _build_prompt(self, user_msg: str, recent_history: str) -> str:
        """构建查询重写的提示词。"""
        return f"""You are a query rewriting assistant. Rewrite the user's question to be more suitable for semantic search.

Recent conversation context:
{recent_history[:500]}

User's question: {user_msg}

Output the rewritten query in JSON format:
{{"query": "rewritten query text", "needs_search": true/false}}

If the question is a greeting, chit-chat, or doesn't require memory search, set needs_search to false and return the original query."""

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM 进行查询重写。"""
        try:
            response = await self._llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=self._max_tokens,
            )
            return response.content or ""
        except Exception as exc:
            logger.exception("LLM call failed: %s", exc)
            raise

    def _parse_episodic_query(self, raw_output: str) -> str:
        """从 LLM 输出中解析情节性查询。"""
        try:
            import json
            data = json.loads(raw_output)
            if isinstance(data, dict):
                query = data.get("query", "")
                needs_search = data.get("needs_search", True)
                if not needs_search:
                    return ""
                return query or ""
        except Exception:
            logger.debug("Failed to parse episodic query, using raw output")
        return raw_output.strip()

    async def _rewrite_procedure_query(self, user_msg: str) -> str:
        """重写程序性查询。"""
        # 简单实现：检查程序性相关关键词
        procedure_keywords = ["how to", "how do i", "steps to", "process", "workflow"]
        lowered = user_msg.lower()
        if any(keyword in lowered for keyword in procedure_keywords):
            return user_msg
        return ""

