"""配置驱动的渠道注册与生命周期服务。

本模块是组合根使用渠道层的唯一入口。它只负责创建和管理适配器，不处理
平台消息内容，也不承载对话业务。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from infra.config import ChannelsConfig
from interfaces.channels.base import ChannelAdapter, ChannelContext


logger = logging.getLogger(__name__)
ChannelFactory = Callable[[Mapping[str, object], ChannelContext], ChannelAdapter]


@dataclass
class ChannelService:
    """渠道注册表、实例工厂和统一生命周期协调器。"""

    _factories: dict[str, ChannelFactory] = field(default_factory=dict)
    _adapters: list[ChannelAdapter] = field(default_factory=list)
    _started: list[ChannelAdapter] = field(default_factory=list)
    _context: ChannelContext | None = None

    def register(self, name: str, factory: ChannelFactory) -> None:
        """注册一个唯一的渠道工厂。"""

        clean_name = name.strip()
        if not clean_name:
            raise ValueError("渠道名称不能为空")
        if clean_name in self._factories:
            raise ValueError(f"渠道已注册: {clean_name}")
        self._factories[clean_name] = factory

    def build_enabled(
        self,
        configs: ChannelsConfig,
        context: ChannelContext,
    ) -> None:
        """根据配置创建启用的渠道适配器。"""

        if self._adapters:
            raise RuntimeError("渠道实例已经构建")
        self._context = context
        for name, raw_options in configs.adapters.items():
            options = dict(raw_options)
            if not bool(options.get("enabled", False)):
                continue
            factory = self._factories.get(name)
            if factory is None:
                raise ValueError(f"未注册的渠道: {name}")
            try:
                adapter = factory(options, context)
            except Exception as exc:
                raise RuntimeError(f"构造渠道失败: {name}: {exc}") from exc
            if adapter.name != name:
                raise ValueError(
                    f"渠道工厂名称不一致: 注册名={name}, 适配器名={adapter.name}"
                )
            self._adapters.append(adapter)

    def start_all(self) -> None:
        """按注册顺序启动渠道；失败时逆序回滚已启动渠道。"""

        if self._started:
            return
        started: list[ChannelAdapter] = []
        try:
            for adapter in self._adapters:
                if self._context is None:
                    raise RuntimeError("渠道服务缺少运行时上下文")
                adapter.start(self._context)
                started.append(adapter)
            self._started = started
        except Exception:
            for adapter in reversed(started):
                try:
                    adapter.stop()
                except Exception:
                    logger.exception("渠道启动回滚失败: %s", adapter.name)
            raise

    def stop_all(self) -> None:
        """逆序停止所有已经启动的渠道。"""

        failures: list[Exception] = []
        for adapter in reversed(self._started):
            try:
                adapter.stop()
            except (Exception, KeyboardInterrupt) as exc:
                failures.append(exc)
                logger.exception("渠道停止失败: %s", adapter.name)
        self._started.clear()
        if failures:
            raise RuntimeError(f"{len(failures)} 个渠道停止失败") from failures[0]

    def join_all(self, timeout: float | None = None) -> None:
        """等待所有渠道内部 worker 结束。"""

        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        for adapter in reversed(self._adapters):
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.monotonic())
            adapter.join(remaining)

    def adapters(self) -> tuple[ChannelAdapter, ...]:
        """返回当前已构建的渠道实例快照。"""

        return tuple(self._adapters)


def register_builtin_channels(service: ChannelService) -> None:
    """注册项目内置渠道。

    导入放在函数内部，避免渠道模块在应用启动前被强制加载；新增 IM 时只需
    增加一个适配器模块和一个工厂注册，不需要修改应用业务代码。
    """

    from interfaces.channels.cli import CLIChannel
    from interfaces.channels.http import HTTPChannel
    from interfaces.channels.qq import QQChannel
    from interfaces.channels.qqbot import QQBotChannel
    from interfaces.channels.telegram import TelegramChannel
    from infra.security import APIKeyAuth

    def text(value: object, default: str = "") -> str:
        return str(value if value is not None else default)

    def integer(value: object, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def string_list(value: object) -> list[str]:
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in text(value).split(",") if item.strip()]

    def integer_set(value: object) -> set[int]:
        result: set[int] = set()
        for item in string_list(value):
            try:
                result.add(int(item))
            except ValueError:
                continue
        return result

    def build_cli(options: Mapping[str, object], context: ChannelContext) -> ChannelAdapter:
        del context
        return CLIChannel(default_session_id=text(options.get("default_session_id"), "default"))

    def build_http(options: Mapping[str, object], context: ChannelContext) -> ChannelAdapter:
        del context
        api_key = text(options.get("api_key")) or None
        return HTTPChannel(
            host=text(options.get("host"), "127.0.0.1"),
            port=integer(options.get("port"), 8788),
            auth=APIKeyAuth(api_key),
        )

    def build_telegram(options: Mapping[str, object], context: ChannelContext) -> ChannelAdapter:
        return TelegramChannel(
            bot_token=text(options.get("bot_token")),
            allowed_users=string_list(options.get("allowed_users")),
            allowed_groups=list(integer_set(options.get("allowed_groups"))),
            attachment_dir=context.attachment_dir / "telegram",
        )

    def build_qq(options: Mapping[str, object], context: ChannelContext) -> ChannelAdapter:
        del context
        return QQChannel(
            host=text(options.get("host"), "127.0.0.1"),
            port=integer(options.get("port"), 5700),
            api_base=text(options.get("api_base"), "http://127.0.0.1:5700"),
            access_token=text(options.get("access_token")),
        )

    def build_qqbot(options: Mapping[str, object], context: ChannelContext) -> ChannelAdapter:
        del context
        return QQBotChannel(
            app_id=text(options.get("app_id")),
            token=text(options.get("token")),
            secret=text(options.get("secret")),
            allowed_users=integer_set(options.get("allowed_users")),
            allowed_groups=integer_set(options.get("allowed_groups")),
        )

    service.register("cli", build_cli)
    service.register("http", build_http)
    service.register("telegram", build_telegram)
    service.register("qq", build_qq)
    service.register("qqbot", build_qqbot)
