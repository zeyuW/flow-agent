"""ProactiveLoop: 基于霍克斯过程模型的自适应间隔循环 (spec proactive)。"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Callable

from flow_agent.proactive.mcp_pool import McpClientPool
from flow_agent.proactive.proactive_pipeline import ProactiveTurnPipeline

logger = logging.getLogger(__name__)


@dataclass
class HawkesConfig:
    """霍克斯过程配置参数。"""
    # 基础心跳强度（例如深夜 μ 极低，白天较高）
    base_intensity: float = 0.1
    # 自激强度（用户说一句话，激起 Agent 的兴奋度度量）
    excitation_alpha: float = 0.5
    # 衰减速率
    decay_beta: float = 0.1
    # 基准时间常数
    time_constant: float = 60.0  # 秒
    # 最小 tick 间隔（秒）
    min_interval: float = 60.0
    # 最大 tick 间隔（秒）
    max_interval: float = 1800.0


@dataclass
class InteractionEvent:
    """用户交互事件。"""
    timestamp: float
    event_type: str = "message"  # message, reaction, etc.


class HawkesProcessModel:
    """霍克斯过程模型：捕捉用户交互的"爆发性/群聚性"特征。

    核心思想：每一次历史事件的发生，都会在短期内提高未来事件发生的概率，
    然后该影响随时间指数衰减。
    """

    def __init__(self, config: HawkesConfig) -> None:
        self._config = config
        self._events: list[InteractionEvent] = []
        self._last_tick_time: float = 0.0

    def add_interaction(self, event_type: str = "message") -> None:
        """记录用户交互事件。"""
        event = InteractionEvent(timestamp=time.time(), event_type=event_type)
        self._events.append(event)
        logger.debug(f"添加交互事件: {event_type} at {event.timestamp}")
        # 清理旧事件（保留最近 24 小时）
        self._cleanup_old_events()

    def _cleanup_old_events(self, max_age: float = 86400.0) -> None:
        """清理过旧的事件记录。"""
        current_time = time.time()
        self._events = [
            e for e in self._events
            if current_time - e.timestamp < max_age
        ]

    def _compute_base_intensity(self, current_time: float) -> float:
        """计算基础心跳强度 μ(t)。

        简化实现：根据时间段调整基础强度
        - 白天 (8:00-22:00): 基础强度较高
        - 深夜 (22:00-8:00): 基础强度较低
        """
        hour = (current_time % 86400) / 3600  # 转换为小时
        if 8 <= hour < 22:
            # 白天
            return self._config.base_intensity * 1.5
        else:
            # 深夜
            return self._config.base_intensity * 0.5

    def _compute_intensity(self, current_time: float) -> float:
        """计算当前时刻 t 的主动 Tick 强度 λ(t)。

        λ(t) = μ(t) + Σ α × e^(-β × (t - ti))
               ti < t
        """
        # 基础心跳强度
        base_mu = self._compute_base_intensity(current_time)

        # 自激项：所有历史事件的贡献
        excitation_sum = 0.0
        for event in self._events:
            time_diff = current_time - event.timestamp
            if time_diff > 0:
                excitation = self._config.excitation_alpha * math.exp(
                    -self._config.decay_beta * time_diff
                )
                excitation_sum += excitation

        total_intensity = base_mu + excitation_sum
        return total_intensity

    def compute_next_interval(self) -> float:
        """计算下一个 Tick 的延迟。

        Next_Tick = C / λ(t)
        """
        current_time = time.time()
        intensity = self._compute_intensity(current_time)

        # 计算下一个 tick 间隔
        next_interval = self._config.time_constant / intensity

        # 限制在最小和最大间隔之间
        next_interval = max(
            self._config.min_interval,
            min(self._config.max_interval, next_interval)
        )

        self._last_tick_time = current_time

        logger.debug(
            f"强度: {intensity:.4f}, 下一个间隔: {next_interval:.2f}s"
        )
        return next_interval

    def get_current_intensity(self) -> float:
        """获取当前强度（用于调试）。"""
        return self._compute_intensity(time.time())

    def get_event_count(self, window_seconds: float = 3600.0) -> int:
        """获取指定时间窗口内的事件数量。"""
        current_time = time.time()
        return sum(
            1 for e in self._events
            if current_time - e.timestamp < window_seconds
        )

    def reset(self) -> None:
        """重置模型状态。"""
        self._events = []
        self._last_tick_time = 0.0
        logger.info("霍克斯过程模型已重置")


class ProactiveLoop:
    """主动循环：基于霍克斯过程模型的自适应间隔，MCP 连接池，Tick 分发 (spec proactive)。"""

    def __init__(
        self,
        pipeline: ProactiveTurnPipeline,
        mcp_pool: McpClientPool,
        *,
        chat_id: str = "",
        min_interval: float = 60.0,
        max_interval: float = 1800.0,
        is_busy_fn = None,
        hawkes_config: HawkesConfig | None = None,
        polling_module=None,
    ) -> None:
        self._pipeline = pipeline
        self._pool = mcp_pool
        self._chat_id = chat_id
        self._min_interval = min_interval
        self._max_interval = max_interval
        self._is_busy_fn = is_busy_fn
        self._running = False
        self._task: asyncio.Task | None = None
        self._polling_module = polling_module

        # 霍克斯过程模型
        if hawkes_config is None:
            hawkes_config = HawkesConfig(
                min_interval=min_interval,
                max_interval=max_interval,
            )
        self._hawkes = HawkesProcessModel(hawkes_config)

    async def run(self) -> None:
        """启动主动循环，使用霍克斯过程模型。"""
        self._running = True

        # 连接 MCP 连接池
        try:
            await self._pool.connect_all()
        except Exception:
            logger.exception("MCP 连接池连接失败")

        # 启动 MCP 轮询模块（如果有）
        if self._polling_module:
            try:
                await self._polling_module.start()
                logger.info("MCP 轮询模块已启动")
            except Exception:
                logger.exception("MCP 轮询模块启动失败")

        # 主自适应循环，使用霍克斯过程
        await self._run_loop()

    async def _run_loop(self) -> None:
        """主循环：使用霍克斯过程模型计算 tick 间隔。"""
        logger.info("主动回复循环启动")
        while self._running:
            # 检查是否忙碌
            is_busy = self._is_busy_fn() if self._is_busy_fn else False
            logger.debug(f"主动回复 tick 开始: chat_id={self._chat_id}, is_busy={is_busy}")
            
            # 执行 tick
            tick = await self._pipeline.run(
                chat_id=self._chat_id,
                base_score=-1.0,  # 霍克斯模型不需要 base_score，使用 -1 跳过概率检查
                is_busy=is_busy,
            )
            
            logger.info(f"主动回复 tick 完成: gate_passed={tick.gate_result.passed if tick.gate_result else False}, reason={tick.gate_result.reason if tick.gate_result else 'no_gate'}")

            # 如果 tick 通过，记录为一次交互事件
            if tick.gate_result and tick.gate_result.passed:
                self._hawkes.add_interaction("proactive_tick")
                logger.info("主动回复 tick 通过，记录交互事件")

            # 使用霍克斯过程模型计算下一个 tick 间隔
            next_interval = self._hawkes.compute_next_interval()
            
            logger.info(
                f"霍克斯过程: 强度={self._hawkes.get_current_intensity():.4f}, "
                f"下一个间隔={next_interval:.2f}s, "
                f"最近1小时事件数={self._hawkes.get_event_count(3600)}"
            )

            await asyncio.sleep(next_interval)

    async def stop(self) -> None:
        """停止主动循环。"""
        self._running = False
        if self._task:
            self._task.cancel()

        # 停止 MCP 轮询模块（如果有）
        if self._polling_module:
            try:
                await self._polling_module.stop()
                logger.info("MCP 轮询模块已停止")
            except Exception:
                logger.exception("MCP 轮询模块停止失败")

        await self._pool.close_all()

    async def start_background(self) -> asyncio.Task:
        """作为后台任务启动循环。"""
        self._task = asyncio.create_task(self.run(), name="proactive_loop")
        return self._task

    def record_user_interaction(self, event_type: str = "message") -> None:
        """记录用户交互事件（供外部调用）。"""
        self._hawkes.add_interaction(event_type)
        logger.debug(f"记录用户交互: {event_type}")

    def get_current_intensity(self) -> float:
        """获取当前强度（用于监控）。"""
        return self._hawkes.get_current_intensity()

    def get_next_interval(self) -> float:
        """获取下一个 tick 间隔（用于监控）。"""
        return self._hawkes.compute_next_interval()
