"""配置加载器：仅从 config.toml 加载 Settings，不再使用环境变量。"""

from pathlib import Path
from typing import Any

from flow_agent.config.settings import (
    ChannelsSettings,
    DelegationPolicySettings,
    DriftSettings,
    JobsSettings,
    LoggingSettings,
    MemoryPolicySettings,
    ObserveSettings,
    PersonaSettings,
    PromptBudgetSettings,
    ProactiveSettings,
    RetrievalSettings,
    SessionSettings,
    Settings,
    StorageSettings,
    SubagentSettings,
    ToolingSettings,
)
from flow_agent.config.source_values import ConfigValues
from flow_agent.llm.config import build_llm_model_settings, build_llm_provider_settings

_SETTINGS_CACHE: Settings | None = None


def clear_settings_cache() -> None:
    global _SETTINGS_CACHE
    _SETTINGS_CACHE = None


def load_settings(*, force_reload: bool = False) -> Settings:
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None and not force_reload:
        return _SETTINGS_CACHE


    def _as_dict(path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        suffix = path.suffix.lower()
        if suffix == ".toml":
            try:
                import tomli as _toml
            except ModuleNotFoundError:
                try:
                    import tomllib as _toml
                except ModuleNotFoundError:
                    return {}
            raw = _toml.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml
            except ModuleNotFoundError:
                return {}
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        return {}

    project_root = Path(__file__).resolve().parents[2]
    
    # 默认从项目根目录的 config.toml 读取
    config_path = project_root / "config.toml"
    
    external_config = _as_dict(config_path)
    
    values = ConfigValues(
        external_config=external_config,
        project_root=project_root,
    )

    # 验证必要配置
    _validate_required_config(values)

    settings = Settings(
        model=build_llm_model_settings(values),
        storage=StorageSettings(
            memory_db_path=values.get_str(
                ("storage", "memory_db_path"),
                str(project_root / ".flow" / "memory.db"),
            ),
        ),
        logging=LoggingSettings(
            level=values.get_str(("logging", "level"), "INFO"),
        ),
        session=SessionSettings(
            default_session_id=values.get_str(
                ("session", "default_session_id"),
                "default",
            ),
            max_history_messages=values.get_int(
                ("session", "max_history_messages"),
                500,
                minimum=1,
            ),
            cache_size=values.get_int(
                ("session", "cache_size"),
                64,
                minimum=1,
            ),
            undo_enabled=values.get_bool(
                ("session", "undo_enabled"),
                True,
            ),
            tool_result_max_chars=values.get_int(
                ("session", "tool_result_max_chars"),
                10000,
                minimum=100,
            ),
        ),
        tooling=ToolingSettings(
            enabled=values.get_bool(("tooling", "enabled"), True),
            max_tool_steps=values.get_int(
                ("tooling", "max_tool_steps"),
                5,
                minimum=1,
            ),
            tool_selection_max=values.get_int(
                ("tooling", "tool_selection_max"),
                8,
                minimum=1,
            ),
        ),
        retrieval=RetrievalSettings(
            enabled=values.get_bool(("retrieval", "enabled"), True),
            max_items=values.get_int(
                ("retrieval", "max_items"),
                6,
                minimum=1,
            ),
            min_score=values.get_float(
                ("retrieval", "min_score"),
                0.18,
                minimum=0.0,
                maximum=1.0,
            ),
        ),
        observe=ObserveSettings(
            enabled=values.get_bool(("observe", "enabled"), True),
            trace_path=values.get_str(
                ("observe", "trace_path"),
                str(project_root / ".flow" / "trace.jsonl"),
            ),
        ),
        memory_policy=MemoryPolicySettings(
            enabled=values.get_bool(
                ("memory_policy", "enabled"),
                True,
            ),
            max_messages=values.get_int(
                ("memory_policy", "max_messages"),
                200,
                minimum=1,
            ),
            dedupe=values.get_bool(
                ("memory_policy", "dedupe"),
                True,
            ),
        ),
        proactive=ProactiveSettings(
            enabled=values.get_bool(("proactive", "enabled"), False),
            max_per_day=values.get_int(
                ("proactive", "max_per_day"),
                5,
                minimum=1,
            ),
            min_interval=values.get_float(
                ("proactive", "min_interval"),
                60.0,
                minimum=1.0,
            ),
            max_interval=values.get_float(
                ("proactive", "max_interval"),
                1800.0,
                minimum=1.0,
            ),
            cooldown=values.get_float(
                ("proactive", "cooldown"),
                120.0,
                minimum=0.0,
            ),
            judge_model=values.prefixed_str(
                ("proactive", "judge_model"),
                "",
            ),
            hawkes_enabled=values.get_bool(
                ("proactive", "hawkes_enabled"),
                True,
            ),
            hawkes_base_intensity=values.get_float(
                ("proactive", "hawkes_base_intensity"),
                0.1,
                minimum=0.0,
            ),
            hawkes_excitation_alpha=values.get_float(
                ("proactive", "hawkes_excitation_alpha"),
                0.5,
                minimum=0.0,
            ),
            hawkes_decay_beta=values.get_float(
                ("proactive", "hawkes_decay_beta"),
                0.1,
                minimum=0.0,
            ),
            hawkes_time_constant=values.get_float(
                ("proactive", "hawkes_time_constant"),
                60.0,
                minimum=1.0,
            ),
            telegram_target_user_id=values.get_str(
                ("proactive", "telegram_target_user_id"),
                "",
            ),
        ),
        drift=DriftSettings(
            enabled=values.get_bool(("drift", "enabled"), False),
            data_dir=values.get_str(
                ("drift", "data_dir"),
                str(project_root / ".flow" / "drift"),
            ),
            min_interval_hours=values.get_float(
                ("drift", "min_interval_hours"),
                1.0,
                minimum=0.1,
            ),
            max_steps=values.get_int(
                ("drift", "max_steps"), 10, minimum=1
            ),
        ),
        channels=ChannelsSettings(
            # Web 控制台
            dashboard_enabled=values.get_bool(("channels", "dashboard_enabled"), False),
            dashboard_host=values.get_str(("channels", "dashboard_host"), "127.0.0.1"),
            dashboard_port=values.get_int(("channels", "dashboard_port"), 8787),
            # HTTP API（Web 页面后端）
            http_enabled=values.get_bool(("channels", "http_enabled"), False),
            http_host=values.get_str(("channels", "http_host"), "127.0.0.1"),
            http_port=values.get_int(("channels", "http_port"), 8788),
            # Telegram Bot
            telegram_enabled=values.get_bool(("channels", "telegram_enabled"), False),
            telegram_bot_token=values.get_str(("channels", "telegram_bot_token"), ""),
            telegram_allowed_users=values.get_str(("channels", "telegram_allowed_users"), ""),
            telegram_allowed_groups=values.get_str(("channels", "telegram_allowed_groups"), ""),
        ),
        jobs=JobsSettings(
            max_async_queue=values.get_int(
                ("jobs", "max_async_queue"), 64, minimum=1
            ),
            timeout_seconds=values.get_float(
                ("jobs", "timeout_seconds"), 30.0, minimum=0.1
            ),
        ),
        subagent=SubagentSettings(
            max_concurrency=values.get_int(
                ("subagent", "max_concurrency"), 2, minimum=1
            ),
            tasks_file=values.get_str(
                ("subagent", "tasks_file"),
                str(project_root / ".flow" / "subagent_tasks.jsonl"),
            ),
        ),
        persona=PersonaSettings(
            name=values.get_str(("persona", "name"), "FlowAgent"),
            passive_tone=values.get_str(
                ("persona", "passive_tone"), "professional, concise, helpful"
            ),
            proactive_tone=values.get_str(
                ("persona", "proactive_tone"), "friendly, brief, actionable"
            ),
            style=values.get_str(("persona", "style"), "structured"),
        ),
        provider=build_llm_provider_settings(values),
        prompt_budget=PromptBudgetSettings(
            max_chars=values.get_int(
                ("prompt_budget", "max_chars"), 8000, minimum=2000
            ),
            history_chars=values.get_int(
                ("prompt_budget", "history_chars"), 3000, minimum=500
            ),
            memory_chars=values.get_int(
                ("prompt_budget", "memory_chars"), 1500, minimum=200
            ),
            tool_trace_chars=values.get_int(
                ("prompt_budget", "tool_trace_chars"), 1000, minimum=200
            ),
        ),
        delegation_policy=DelegationPolicySettings(
            max_local_chars=values.get_int(
                ("delegation_policy", "max_local_chars"), 500, minimum=100
            ),
            enabled=values.get_bool(
                ("delegation_policy", "enabled"), True
            ),
        )
    )
    _SETTINGS_CACHE = settings
    return settings


def _validate_required_config(values: ConfigValues) -> None:
    """验证必要的配置项，如果缺失则抛出错误。"""
    # LLM 配置
    api_key = values.get_str(("llm", "main", "api_key"), "")
    if not api_key:
        raise ValueError("llm.main.api_key is required in config.toml")
    
    # Telegram 配置（如果启用）
    telegram_enabled = values.get_bool(("channels", "telegram_enabled"), False)
    if telegram_enabled:
        bot_token = values.get_str(("channels", "telegram_bot_token"), "")
        if not bot_token:
            raise ValueError("channels.telegram_bot_token is required when telegram_enabled is true")
        allowed_users = values.get_str(("channels", "telegram_allowed_users"), "")
        if not allowed_users:
            raise ValueError("channels.telegram_allowed_users is required when telegram_enabled is true")
    
    # 主动推送配置（如果启用）
    proactive_enabled = values.get_bool(("proactive", "enabled"), False)
    if proactive_enabled:
        target_id = values.get_str(("proactive", "telegram_target_user_id"), "")
        if not target_id:
            raise ValueError("proactive.telegram_target_user_id is required when proactive.enabled is true")
