"""插件基类，支持自动注册、7 个阶段方法、initialize()。"""

from pathlib import Path

from flow_agent.plugins.plugin_context import PluginConfig, PluginContext, PluginKVStore
from flow_agent.plugins.plugin_registry import plugin_registry


class Plugin:
    """所有插件的基类。子类通过 __init_subclass__ 自动注册。"""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        plugin_registry.register_class(cls)

    def __init__(self) -> None:
        self.context: PluginContext | None = None
        self._plugin_dir: Path | None = None

    # ── 7 个阶段模块方法 ──

    def before_turn_modules(self) -> list:  # PhaseModule instances
        return []

    def before_reasoning_modules(self) -> list:
        return []

    def prompt_render_modules(self) -> list:
        return []

    def reasoner_modules(self) -> list:
        return []

    def after_reasoning_modules(self) -> list:
        return []

    def after_turn_modules(self) -> list:
        return []

    def turn_started_modules(self) -> list:
        return []

    # ── 主动回复数据源 ──

    def proactive_sources(self) -> list:
        """声明主动推送数据源。
        
        返回 ProactiveSourceSpec 列表，用于插件声明数据源配置。
        默认返回空列表，子类可覆盖。
        """
        return []

    # ── Lifecycle ──

    async def initialize(self) -> None:
        """异步初始化钩子。在 PluginContext 注入后调用。"""

    async def shutdown(self) -> None:
        """Cleanup hook."""

    # ── 上下文注入 ──

    def _inject_context(self, ctx: PluginContext, plugin_dir: Path) -> None:
        self.context = ctx
        self._plugin_dir = plugin_dir
        data_dir = ctx.data_dir or plugin_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        if ctx.kv_store is None:
            ctx.kv_store = PluginKVStore(data_dir / ".kv.json")
        if isinstance(ctx.config, PluginConfig) and not ctx.config._values:
            ctx.config = PluginConfig.load(plugin_dir)
