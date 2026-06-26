"""配置加载器：从 env / .env / 外部 TOML 加载 Settings。"""

import os
from pathlib import Path
import re
from typing import Any

try:
    from dotenv import load_dotenv as _load_dotenv
except ModuleNotFoundError:
    _load_dotenv = None

from flow_agent.config.settings import (
    ChannelsSettings,
    ConfigGovernanceSettings,
    DelegationPolicySettings,
    DriftSettings,
    JobsSettings,
    LoggingSettings,
    MCPServerSettings,
    MCPSettings,
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

    def _expand_env_refs(value: Any) -> Any:
        if isinstance(value, str):
            pattern = re.compile(r"\$\{([A-Z0-9_]+)\}")
            return pattern.sub(lambda m: os.getenv(m.group(1), ""), value)
        if isinstance(value, list):
            return [_expand_env_refs(item) for item in value]
        if isinstance(value, dict):
            return {key: _expand_env_refs(val) for key, val in value.items()}
        return value

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
            return _expand_env_refs(raw) if isinstance(raw, dict) else {}
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml
            except ModuleNotFoundError:
                return {}
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            return _expand_env_refs(raw) if isinstance(raw, dict) else {}
        return {}

    project_root = Path(__file__).resolve().parents[2]
    if _load_dotenv is not None:
        _load_dotenv(project_root / ".env")
    external_path = os.getenv("FLOW_AGENT_CONFIG_FILE", "")
    external_config = _as_dict(Path(external_path)) if external_path else {}
    values = ConfigValues(
        env=dict(os.environ),
        external_config=external_config,
        project_root=project_root,
        external_path=external_path,
    )

    settings = Settings(
        model=build_llm_model_settings(values),
        storage=StorageSettings(
            memory_db_path=values.get_str(
                "FLOW_AGENT_STORAGE_MEMORY_DB_PATH",
                ("storage", "memory_db_path"),
                str(project_root / ".flow" / "memory.db"),
            )
        ),
        logging=LoggingSettings(
            level=values.get_str("FLOW_AGENT_LOG_LEVEL", ("logging", "level"), "INFO")
        ),
        session=SessionSettings(
            default_session_id=values.get_str(
                "FLOW_AGENT_SESSION_DEFAULT_ID",
                ("session", "default_session_id"),
                "default",
            ),
        ),
        tooling=ToolingSettings(
            enabled=values.get_bool("FLOW_AGENT_TOOLING_ENABLED", ("tooling", "enabled"), True),
            max_tool_steps=values.get_int(
                "FLOW_AGENT_TOOLING_MAX_STEPS", ("tooling", "max_tool_steps"), 5, minimum=1
            ),
        ),
        retrieval=RetrievalSettings(
            enabled=values.get_bool("FLOW_AGENT_RETRIEVAL_ENABLED", ("retrieval", "enabled"), True),
            max_items=values.get_int(
                "FLOW_AGENT_RETRIEVAL_MAX_ITEMS", ("retrieval", "max_items"), 6, minimum=0
            ),
        ),
        observe=ObserveSettings(
            enabled=values.get_bool("FLOW_AGENT_OBSERVE_ENABLED", ("observe", "enabled"), True),
            trace_path=values.get_str(
                "FLOW_AGENT_OBSERVE_TRACE_PATH",
                ("observe", "trace_path"),
                str(project_root / ".flow" / "trace.jsonl"),
            ),
        ),
        memory_policy=MemoryPolicySettings(
            enabled=values.get_bool(
                "FLOW_AGENT_MEMORY_POLICY_ENABLED", ("memory_policy", "enabled"), True
            ),
            max_messages=values.get_int(
                "FLOW_AGENT_MEMORY_MAX_MESSAGES", ("memory_policy", "max_messages"), 200, minimum=1
            ),
            dedupe=values.get_bool(
                "FLOW_AGENT_MEMORY_DEDUPE", ("memory_policy", "dedupe"), True
            ),
        ),
        proactive=ProactiveSettings(
            enabled=values.get_bool(
                "FLOW_AGENT_PROACTIVE_ENABLED", ("proactive", "enabled"), False
            ),
            max_per_day=values.get_int(
                "FLOW_AGENT_PROACTIVE_MAX_PER_DAY", ("proactive", "max_per_day"), 5, minimum=0
            ),
            min_interval=values.get_float(
                "FLOW_AGENT_PROACTIVE_MIN_INTERVAL", ("proactive", "min_interval"), 30.0, minimum=1.0
            ),
            max_interval=values.get_float(
                "FLOW_AGENT_PROACTIVE_MAX_INTERVAL", ("proactive", "max_interval"), 300.0, minimum=10.0
            ),
            cooldown=values.get_float(
                "FLOW_AGENT_PROACTIVE_COOLDOWN", ("proactive", "cooldown"), 120.0, minimum=0.0
            ),
            judge_model=values.get_str(
                "FLOW_AGENT_PROACTIVE_JUDGE_MODEL", ("proactive", "judge_model"), ""
            ) or None,
        ),
        drift=DriftSettings(
            enabled=values.get_bool("FLOW_AGENT_DRIFT_ENABLED", ("drift", "enabled"), False),
            data_dir=values.get_str(
                "FLOW_AGENT_DRIFT_DATA_DIR",
                ("drift", "data_dir"),
                str(project_root / ".flow" / "drift"),
            ),
            min_interval_hours=values.get_float(
                "FLOW_AGENT_DRIFT_MIN_INTERVAL_HOURS",
                ("drift", "min_interval_hours"),
                1.0,
                minimum=0.1,
            ),
            max_steps=values.get_int(
                "FLOW_AGENT_DRIFT_MAX_STEPS", ("drift", "max_steps"), 10, minimum=1
            ),
        ),
        channels=ChannelsSettings(
            cli_enabled=values.get_bool(
                "FLOW_AGENT_CHANNEL_CLI_ENABLED", ("channels", "cli_enabled"), True
            ),
            http_enabled=values.get_bool(
                "FLOW_AGENT_CHANNEL_HTTP_ENABLED", ("channels", "http_enabled"), False
            ),
            http_host=values.get_str(
                "FLOW_AGENT_CHANNEL_HTTP_HOST", ("channels", "http_host"), "127.0.0.1"
            ),
            http_port=values.get_int(
                "FLOW_AGENT_CHANNEL_HTTP_PORT", ("channels", "http_port"), 8788
            ),
            dashboard_enabled=values.get_bool(
                "FLOW_AGENT_CHANNEL_DASHBOARD_ENABLED", ("channels", "dashboard_enabled"), False
            ),
            dashboard_host=values.get_str(
                "FLOW_AGENT_CHANNEL_DASHBOARD_HOST", ("channels", "dashboard_host"), "127.0.0.1"
            ),
            dashboard_port=values.get_int(
                "FLOW_AGENT_CHANNEL_DASHBOARD_PORT", ("channels", "dashboard_port"), 8787
            ),
            qq_enabled=values.get_bool(
                "FLOW_AGENT_CHANNEL_QQ_ENABLED", ("channels", "qq_enabled"), False
            ),
            qq_host=values.get_str(
                "FLOW_AGENT_CHANNEL_QQ_HOST", ("channels", "qq_host"), "127.0.0.1"
            ),
            qq_port=values.get_int(
                "FLOW_AGENT_CHANNEL_QQ_PORT", ("channels", "qq_port"), 8790
            ),
            qq_api_base=values.get_str(
                "FLOW_AGENT_CHANNEL_QQ_API_BASE", ("channels", "qq_api_base"), "http://127.0.0.1:3000"
            ),
            qq_access_token=values.get_str(
                "FLOW_AGENT_CHANNEL_QQ_ACCESS_TOKEN", ("channels", "qq_access_token"), ""
            ),
            qqbot_app_id=values.get_str(
                "FLOW_AGENT_CHANNEL_QQBOT_APP_ID", ("channels", "qqbot_app_id"), ""
            ),
            qqbot_token=values.get_str(
                "FLOW_AGENT_CHANNEL_QQBOT_TOKEN", ("channels", "qqbot_token"), ""
            ),
            qqbot_secret=values.get_str(
                "FLOW_AGENT_CHANNEL_QQBOT_SECRET", ("channels", "qqbot_secret"), ""
            ),
            qqbot_allowed_users=values.get_str(
                "FLOW_AGENT_CHANNEL_QQBOT_ALLOWED_USERS", ("channels", "qqbot_allowed_users"), ""
            ),
            qqbot_allowed_groups=values.get_str(
                "FLOW_AGENT_CHANNEL_QQBOT_ALLOWED_GROUPS", ("channels", "qqbot_allowed_groups"), ""
            ),
        ),
        jobs=JobsSettings(
            max_async_queue=values.get_int(
                "FLOW_AGENT_JOBS_MAX_ASYNC_QUEUE", ("jobs", "max_async_queue"), 64, minimum=1
            ),
            timeout_seconds=values.get_float(
                "FLOW_AGENT_JOBS_TIMEOUT_SECONDS", ("jobs", "timeout_seconds"), 30.0, minimum=0.1
            ),
        ),
        subagent=SubagentSettings(
            max_concurrency=values.get_int(
                "FLOW_AGENT_SUBAGENT_MAX_CONCURRENCY", ("subagent", "max_concurrency"), 2, minimum=1
            ),
            tasks_file=values.get_str(
                "FLOW_AGENT_SUBAGENT_TASKS_FILE",
                ("subagent", "tasks_file"),
                str(project_root / ".flow" / "subagent_tasks.jsonl"),
            ),
        ),
        governance=ConfigGovernanceSettings(
            config_version=values.get_str(
                "FLOW_AGENT_CONFIG_VERSION", ("governance", "config_version"), "v1"
            ),
            external_config_path=external_path or None,
        ),
        persona=PersonaSettings(
            name=values.get_str("FLOW_AGENT_PERSONA_NAME", ("persona", "name"), "FlowAgent"),
            passive_tone=values.get_str(
                "FLOW_AGENT_PERSONA_PASSIVE_TONE", ("persona", "passive_tone"), "professional, concise, helpful"
            ),
            proactive_tone=values.get_str(
                "FLOW_AGENT_PERSONA_PROACTIVE_TONE", ("persona", "proactive_tone"), "friendly, brief, actionable"
            ),
            style=values.get_str("FLOW_AGENT_PERSONA_STYLE", ("persona", "style"), "structured"),
        ),
        provider=build_llm_provider_settings(values),
        prompt_budget=PromptBudgetSettings(
            max_chars=values.get_int(
                "FLOW_AGENT_PROMPT_MAX_CHARS", ("prompt_budget", "max_chars"), 8000, minimum=2000
            ),
            history_chars=values.get_int(
                "FLOW_AGENT_PROMPT_HISTORY_CHARS", ("prompt_budget", "history_chars"), 3000, minimum=500
            ),
            memory_chars=values.get_int(
                "FLOW_AGENT_PROMPT_MEMORY_CHARS", ("prompt_budget", "memory_chars"), 1500, minimum=200
            ),
            tool_trace_chars=values.get_int(
                "FLOW_AGENT_PROMPT_TOOL_TRACE_CHARS", ("prompt_budget", "tool_trace_chars"), 1000, minimum=200
            ),
        ),
        delegation_policy=DelegationPolicySettings(
            max_local_chars=values.get_int(
                "FLOW_AGENT_DELEGATION_MAX_LOCAL_CHARS", ("delegation_policy", "max_local_chars"), 500, minimum=100
            ),
            enabled=values.get_bool(
                "FLOW_AGENT_DELEGATION_ENABLED", ("delegation_policy", "enabled"), True
            ),
        ),
        mcp=MCPSettings(
            enabled=values.get_bool("FLOW_AGENT_MCP_ENABLED", ("mcp", "enabled"), False),
            servers=[
                MCPServerSettings(name=name, enabled=True, tools=[])
                for name in values.get_csv("FLOW_AGENT_MCP_SERVERS", ("mcp", "servers"), [])
            ],
        ),
    )
    _SETTINGS_CACHE = settings
    return settings
