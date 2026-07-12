"""Plugin base class with auto-registration, 7 phase methods, initialize() (spec 2a)."""

from pathlib import Path

from flow_agent.plugins.plugin_context import PluginConfig, PluginContext, PluginKVStore
from flow_agent.plugins.plugin_registry import plugin_registry


class Plugin:
    """Base class for all plugins. Subclasses auto-register via __init_subclass__ (spec 1c)."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        plugin_registry.register_class(cls)

    def __init__(self) -> None:
        self.context: PluginContext | None = None
        self._plugin_dir: Path | None = None

    # ── 7 phase module methods (spec 2a) ──

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

    # ── Proactive Sources (参考 akashic-agent) ──

    def proactive_sources(self) -> list:
        """声明主动推送数据源（参考 akashic-agent ProactiveSourceSpec）。
        
        返回 ProactiveSourceSpec 列表，用于插件声明数据源配置。
        默认返回空列表，子类可覆盖。
        """
        return []

    # ── Lifecycle ──

    async def initialize(self) -> None:
        """Async init hook. Called after PluginContext is injected (spec 1e)."""

    async def shutdown(self) -> None:
        """Cleanup hook."""

    # ── Context injection (spec 6b) ──

    def _inject_context(self, ctx: PluginContext, plugin_dir: Path) -> None:
        self.context = ctx
        self._plugin_dir = plugin_dir
        if ctx.kv_store is None:
            ctx.kv_store = PluginKVStore(plugin_dir / ".kv.json")
        if isinstance(ctx.config, PluginConfig) and not ctx.config._values:
            ctx.config = PluginConfig.load(plugin_dir)
