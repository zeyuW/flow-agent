"""共享应用配置、TOML 加载和热更新基础设施。

本模块集中提供所有业务模块共用的配置快照、配置文件加载器和运行时
热更新轮询器；具体业务配置字段仍由 ``AppConfig`` 统一校验。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import sys
import threading
from typing import Any, Protocol

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenConfig(BaseModel):
    """所有运行配置的不可变严格基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelEndpointConfig(FrozenConfig):
    """一个可直接调用的模型端点。"""

    model: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    base_url: str | None = None


class MainModelConfig(ModelEndpointConfig):
    """主模型端点及对话行为参数。"""

    system_prompt: str = "You are a helpful AI assistant."
    enable_thinking: bool = True


class LLMConfig(FrozenConfig):
    """对话、快速判断和视觉模型配置。"""

    main: MainModelConfig
    fast: ModelEndpointConfig | None = None
    vision: ModelEndpointConfig | None = None
    fallback_enabled: bool = True


class EmbeddingConfig(FrozenConfig):
    """嵌入服务配置；空密钥表示沿用主模型凭据。"""

    provider: str = "qwen"
    model: str = "text-embedding-v3"
    api_key: str | None = None
    base_url: str | None = None


class StorageConfig(FrozenConfig):
    """持久化与出站恢复参数。"""

    memory_db_path: str = Field(default=".flow/data/memory.db", min_length=1)
    outbox_recovery_window_seconds: float = Field(default=0.0, ge=0.0)
    outbox_recovery_limit: int = Field(default=100, ge=1)


class LoggingConfig(FrozenConfig):
    """日志输出参数。"""

    level: str = Field(default="INFO", min_length=1)


class SessionConfig(FrozenConfig):
    """会话缓存、历史和撤销参数。"""

    default_session_id: str = Field(default="default", min_length=1)
    max_history_messages: int = Field(default=500, ge=1)
    cache_size: int = Field(default=64, ge=1)
    undo_enabled: bool = True
    tool_result_max_chars: int = Field(default=10000, ge=100)


class ToolingConfig(FrozenConfig):
    """工具选择和执行轮数参数。"""

    enabled: bool = True
    max_tool_steps: int = Field(default=5, ge=1)
    tool_selection_max: int = Field(default=8, ge=1)


class McpConfig(FrozenConfig):
    """MCP 外部工具运行参数。"""

    enabled: bool = True
    startup_timeout_seconds: float = Field(default=30.0, ge=1.0)
    call_timeout_seconds: float = Field(default=60.0, ge=1.0)


class RetrievalConfig(FrozenConfig):
    """检索数量和相关度参数。"""

    enabled: bool = True
    max_items: int = Field(default=5, ge=1)
    min_score: float = Field(default=0.18, ge=0.0, le=1.0)


class ObserveConfig(FrozenConfig):
    """运行追踪参数。"""

    enabled: bool = True
    trace_path: str = Field(default=".flow/logs/trace.jsonl", min_length=1)


class AdminApiConfig(FrozenConfig):
    """本机只读管理 API 的监听配置。"""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=8790, ge=1, le=65535)

    @model_validator(mode="after")
    def validate_local_host(self) -> AdminApiConfig:
        if self.host not in {"127.0.0.1", "localhost"}:
            raise ValueError("管理 API 只能绑定本机地址")
        return self


class MemoryPolicyConfig(FrozenConfig):
    """会话记忆选择策略。"""

    enabled: bool = True
    max_messages: int = Field(default=100, ge=1)
    dedupe: bool = True


class MemoryMaintenanceConfig(FrozenConfig):
    """记忆沉淀与画像优化参数。"""

    enabled: bool = True
    consolidation_min_new_messages: int = Field(default=5, ge=1)
    recent_turns_limit: int = Field(default=8, ge=1)
    optimizer_enabled: bool = True
    optimizer_interval_seconds: int = Field(default=64800, ge=1)


class ProactiveConfig(FrozenConfig):
    """主动消息判断、节流、兴趣和状态参数。"""

    enabled: bool = False
    max_per_day: int = Field(default=10, ge=1)
    min_interval: float = Field(default=60.0, ge=1.0)
    max_interval: float = Field(default=600.0, ge=1.0)
    cooldown: float = Field(default=60.0, ge=0.0)
    judge_model: str | None = None
    hawkes_enabled: bool = True
    hawkes_base_intensity: float = Field(default=2.0, ge=0.0)
    hawkes_excitation_alpha: float = Field(default=0.5, ge=0.0)
    hawkes_decay_beta: float = Field(default=0.1, ge=0.0)
    hawkes_time_constant: float = Field(default=30.0, ge=1.0)
    telegram_target_user_id: str | None = None
    idle_enabled: bool = False
    idle_threshold_minutes: float = Field(default=120.0, ge=1.0)
    interest_topics: tuple[str, ...] = ()
    state_path: str = Field(default=".flow/data/proactive.db", min_length=1)
    trace_path: str = Field(default=".flow/logs/proactive.jsonl", min_length=1)

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> ProactiveConfig:
        if self.min_interval > self.max_interval:
            raise ValueError("主动推送最小间隔不能大于最大间隔")
        if self.enabled and not (self.telegram_target_user_id or "").strip():
            raise ValueError("启用主动推送时必须配置目标用户")
        return self


class DriftConfig(FrozenConfig):
    """漂移任务调度参数。"""

    enabled: bool = True
    data_dir: str = Field(default=".flow/drift", min_length=1)
    min_interval_hours: float = Field(default=24.0, ge=0.1)
    max_steps: int = Field(default=50, ge=1)


class ChannelsConfig(FrozenConfig):
    """按渠道名称保存的动态接入配置。"""

    adapters: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_channel_blocks(cls, value: Any) -> dict[str, Any]:
        """将 TOML 的 `[channels.<name>]` 块收敛到 `adapters`。"""

        if value is None:
            return {"adapters": {}}
        if not isinstance(value, dict):
            raise TypeError("channels 配置必须是对象")
        if "adapters" in value:
            adapters = value["adapters"]
            if not isinstance(adapters, dict):
                raise TypeError("channels.adapters 配置必须是对象")
            return {
                "adapters": {
                    str(name): dict(options) for name, options in adapters.items()
                }
            }
        if any(not isinstance(options, dict) for options in value.values()):
            raise ValueError(
                "channels 配置必须使用 [channels.<渠道名>] 配置块，不能继续使用旧扁平字段"
            )
        return {
            "adapters": {str(name): dict(options) for name, options in value.items()}
        }


class JobsConfig(FrozenConfig):
    """后台异步任务队列参数。"""

    max_async_queue: int = Field(default=64, ge=1)
    max_async_workers: int = Field(default=4, ge=1)
    timeout_seconds: float = Field(default=30.0, ge=0.1)


class SubagentConfig(FrozenConfig):
    """委托子代理的并发与持久化参数。"""

    max_concurrency: int = Field(default=2, ge=1)
    tasks_file: str = Field(default=".flow/sessions/subagent_tasks.jsonl", min_length=1)


class PersonaConfig(FrozenConfig):
    """被动与主动线路共用的人设参数。"""

    name: str = Field(default="FlowAgent", min_length=1)
    passive_tone: str = Field(default="professional, concise, helpful", min_length=1)
    proactive_tone: str = Field(default="friendly, brief, actionable", min_length=1)
    style: str = Field(default="structured", min_length=1)


class PromptBudgetConfig(FrozenConfig):
    """提示词各组成部分的字符预算。"""

    max_chars: int = Field(default=8000, ge=2000)
    history_chars: int = Field(default=3000, ge=500)
    memory_chars: int = Field(default=1500, ge=200)
    tool_trace_chars: int = Field(default=1000, ge=200)


class DelegationPolicyConfig(FrozenConfig):
    """本地处理与委托之间的选择策略。"""

    max_local_chars: int = Field(default=500, ge=100)
    enabled: bool = True


class AppConfig(FrozenConfig):
    """一次加载得到的完整应用配置快照。"""

    llm: LLMConfig
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    tooling: ToolingConfig = Field(default_factory=ToolingConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    observe: ObserveConfig = Field(default_factory=ObserveConfig)
    admin_api: AdminApiConfig = Field(default_factory=AdminApiConfig)
    memory_policy: MemoryPolicyConfig = Field(default_factory=MemoryPolicyConfig)
    memory: MemoryMaintenanceConfig = Field(default_factory=MemoryMaintenanceConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    subagent: SubagentConfig = Field(default_factory=SubagentConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    prompt_budget: PromptBudgetConfig = Field(default_factory=PromptBudgetConfig)
    delegation_policy: DelegationPolicyConfig = Field(
        default_factory=DelegationPolicyConfig
    )


def load_config(path: Path) -> AppConfig:
    """读取唯一 TOML 配置源并返回完整不可变快照。"""

    with path.open("rb") as config_file:
        raw: dict[str, Any] = tomllib.load(config_file)
    return resolve_config_paths(AppConfig.model_validate(raw), path.parent)


def resolve_config_paths(config: AppConfig, root: Path) -> AppConfig:
    """把配置中的相对运行时路径固定到项目根目录。"""

    base = root.resolve()

    def absolute(value: str) -> str:
        path = Path(value)
        return str(path if path.is_absolute() else base / path)

    return config.model_copy(
        update={
            "storage": config.storage.model_copy(
                update={"memory_db_path": absolute(config.storage.memory_db_path)}
            ),
            "observe": config.observe.model_copy(
                update={"trace_path": absolute(config.observe.trace_path)}
            ),
            "proactive": config.proactive.model_copy(
                update={
                    "state_path": absolute(config.proactive.state_path),
                    "trace_path": absolute(config.proactive.trace_path),
                }
            ),
            "drift": config.drift.model_copy(
                update={"data_dir": absolute(config.drift.data_dir)}
            ),
            "subagent": config.subagent.model_copy(
                update={"tasks_file": absolute(config.subagent.tasks_file)}
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class PreparedConfigChange:
    """一个已准备、尚未对运行时生效的配置变更。"""

    commit: Callable[[], None]
    discard: Callable[[], None]


class ConfigApplier(Protocol):
    """把候选快照准备为可原子提交的运行时变更。"""

    def prepare(
        self,
        current: AppConfig,
        candidate: AppConfig,
    ) -> PreparedConfigChange: ...


ConfigLoader = Callable[[Path], AppConfig]
ConfigRevision = bytes | None
logger = logging.getLogger(__name__)


class ConfigWatcher:
    """按文件修订执行配置的两阶段更新。"""

    def __init__(
        self,
        path: Path,
        *,
        current: AppConfig,
        appliers: Sequence[ConfigApplier],
        loader: ConfigLoader = load_config,
    ) -> None:
        self.path = path
        self.current = current
        self.appliers = tuple(appliers)
        self.loader = loader
        self._handled_revision = _file_revision(path)

    def reload_once(self) -> bool:
        """处理一个新修订；成功提交时返回真。"""

        revision = _file_revision(self.path)
        if revision == self._handled_revision:
            return False
        self._handled_revision = revision

        try:
            candidate = self.loader(self.path)
        except Exception:
            logger.exception("候选配置加载失败，继续使用当前运行参数")
            return False

        prepared: list[PreparedConfigChange] = []
        try:
            for applier in self.appliers:
                prepared.append(applier.prepare(self.current, candidate))
        except Exception:
            for change in reversed(prepared):
                try:
                    change.discard()
                except Exception:
                    continue
            logger.exception("候选配置准备失败，继续使用当前运行参数")
            return False

        for change in prepared:
            change.commit()
        self.current = candidate
        return True


class ReloadableConfig(Protocol):
    """可由轮询循环触发一次更新的配置对象。"""

    def reload_once(self) -> bool: ...


class ConfigWatchLoop:
    """以单一守护线程周期触发配置更新。"""

    def __init__(
        self,
        watcher: ReloadableConfig,
        *,
        interval_seconds: float = 1.0,
    ) -> None:
        self.watcher = watcher
        self.interval_seconds = max(0.01, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动轮询线程；重复调用不会创建第二个线程。"""

        if self.is_running:
            return
        self._stop.clear()

        def poll() -> None:
            while not self._stop.wait(self.interval_seconds):
                try:
                    self.watcher.reload_once()
                except Exception:
                    logger.exception("配置轮询执行失败，继续使用当前运行参数")

        self._thread = threading.Thread(
            target=poll,
            name="runtime-config-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止并等待轮询线程退出。"""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 2))
            self._thread = None


def _file_revision(path: Path) -> ConfigRevision:
    try:
        return hashlib.sha256(path.read_bytes()).digest()
    except FileNotFoundError:
        return None
