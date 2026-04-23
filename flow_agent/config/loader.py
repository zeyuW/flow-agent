import os
from pathlib import Path

try:
    from dotenv import load_dotenv as _load_dotenv
except ModuleNotFoundError:
    _load_dotenv = None

from flow_agent.config.settings import (
    LoggingSettings,
    ChannelsSettings,
    JobsSettings,
    SubagentSettings,
    ConfigGovernanceSettings,
    MCPServerSettings,
    MCPSettings,
    MemoryPolicySettings,
    ModelSettings,
    ObserveSettings,
    ProactiveSettings,
    RetrievalSettings,
    SessionSettings,
    Settings,
    StorageSettings,
    ToolingSettings,
)


def load_settings() -> Settings:
    def _to_bool(value: str, default: bool) -> bool:
        if value == "":
            return default
        return value.lower() not in {"0", "false", "no", "off"}

    def _split_csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def _deep_get(data: dict[str, object], *keys: str):
        current: object = data
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _as_dict(path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        suffix = path.suffix.lower()
        if suffix == ".toml":
            try:
                import tomli as _toml  # type: ignore[import-not-found]
            except ModuleNotFoundError:
                try:
                    import tomllib as _toml  # type: ignore[attr-defined]
                except ModuleNotFoundError:
                    return {}
            return _toml.loads(path.read_text(encoding="utf-8"))
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore[import-not-found]
            except ModuleNotFoundError:
                return {}
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        return {}

    project_root = Path(__file__).resolve().parents[2]
    if _load_dotenv is not None:
        _load_dotenv(project_root / ".env")
    external_path = os.getenv("FLOW_AGENT_CONFIG_FILE", "")
    external_config = _as_dict(Path(external_path)) if external_path else {}

    model = ModelSettings(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        system_prompt=os.getenv(
            "LLM_SYSTEM_PROMPT",
            "You are a helpful AI assistant.",
        ),
    )
    storage = StorageSettings(
        memory_db_path=os.getenv("FLOW_AGENT_MEMORY_DB_PATH", "")
        or str(_deep_get(external_config, "storage", "memory_db_path") or "")
        or str(project_root / ".flow_agent" / "memory.db"),
    )
    logging = LoggingSettings(
        level=os.getenv("FLOW_AGENT_LOG_LEVEL", "INFO"),
    )
    session = SessionSettings(
        default_session_id=os.getenv("FLOW_AGENT_DEFAULT_SESSION", "")
        or str(_deep_get(external_config, "session", "default_session_id") or "default"),
    )
    tooling = ToolingSettings(
        enabled=os.getenv("FLOW_AGENT_TOOLS_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"},
        max_tool_steps=max(1, int(os.getenv("FLOW_AGENT_MAX_TOOL_STEPS", "5"))),
    )
    retrieval = RetrievalSettings(
        enabled=os.getenv("FLOW_AGENT_RETRIEVAL_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"},
        max_items=max(0, int(os.getenv("FLOW_AGENT_RETRIEVAL_MAX_ITEMS", "6"))),
    )
    observe = ObserveSettings(
        enabled=os.getenv("FLOW_AGENT_OBSERVE_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"},
        trace_path=os.getenv(
            "FLOW_AGENT_TRACE_PATH",
            str(project_root / ".flow_agent" / "trace.jsonl"),
        ),
    )
    memory_policy = MemoryPolicySettings(
        enabled=os.getenv("FLOW_AGENT_MEMORY_POLICY_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"},
        max_messages=max(1, int(os.getenv("FLOW_AGENT_MEMORY_MAX_MESSAGES", "200"))),
        dedupe=os.getenv("FLOW_AGENT_MEMORY_DEDUPE", "true").lower()
        not in {"0", "false", "no", "off"},
    )
    proactive = ProactiveSettings(
        enabled=os.getenv("FLOW_AGENT_PROACTIVE_ENABLED", "false").lower()
        not in {"0", "false", "no", "off"},
        interval_seconds=max(
            1,
            int(os.getenv("FLOW_AGENT_PROACTIVE_INTERVAL_SECONDS", "60")),
        ),
        cooldown_seconds=max(
            0,
            int(os.getenv("FLOW_AGENT_PROACTIVE_COOLDOWN_SECONDS", "300")),
        ),
        dedup_ttl_seconds=max(
            1,
            int(os.getenv("FLOW_AGENT_PROACTIVE_DEDUP_TTL_SECONDS", "86400")),
        ),
        source_file=os.getenv(
            "FLOW_AGENT_PROACTIVE_SOURCE_FILE",
            str(project_root / ".flow_agent" / "proactive_items.txt"),
        ),
        todo_file=os.getenv(
            "FLOW_AGENT_PROACTIVE_TODO_FILE",
            str(project_root / ".flow_agent" / "todo_items.txt"),
        ),
        tasks_file=os.getenv(
            "FLOW_AGENT_PROACTIVE_TASKS_FILE",
            str(project_root / ".flow_agent" / "tasks.txt"),
        ),
        rss_feed_files=_split_csv(os.getenv("FLOW_AGENT_PROACTIVE_RSS_FEED_FILES", ""))
        or [],
        web_snapshot_files=_split_csv(
            os.getenv("FLOW_AGENT_PROACTIVE_WEB_SNAPSHOT_FILES", "")
        )
        or [],
        skills_dir=os.getenv(
            "FLOW_AGENT_SKILLS_DIR",
            str(project_root / "skills"),
        ),
        min_priority_to_send=float(
            os.getenv("FLOW_AGENT_PROACTIVE_MIN_PRIORITY_TO_SEND", "0.5")
        ),
    )
    channels = ChannelsSettings(
        cli_enabled=_to_bool(
            os.getenv("FLOW_AGENT_CHANNEL_CLI_ENABLED", ""),
            bool(_deep_get(external_config, "channels", "cli_enabled") if _deep_get(external_config, "channels", "cli_enabled") is not None else True),
        ),
        http_enabled=_to_bool(
            os.getenv("FLOW_AGENT_CHANNEL_HTTP_ENABLED", ""),
            bool(_deep_get(external_config, "channels", "http_enabled") if _deep_get(external_config, "channels", "http_enabled") is not None else False),
        ),
        http_host=os.getenv("FLOW_AGENT_CHANNEL_HTTP_HOST", "")
        or str(_deep_get(external_config, "channels", "http_host") or "127.0.0.1"),
        http_port=int(
            os.getenv("FLOW_AGENT_CHANNEL_HTTP_PORT", "")
            or str(_deep_get(external_config, "channels", "http_port") or "8788")
        ),
        dashboard_enabled=_to_bool(
            os.getenv("FLOW_AGENT_CHANNEL_DASHBOARD_ENABLED", ""),
            bool(_deep_get(external_config, "channels", "dashboard_enabled") if _deep_get(external_config, "channels", "dashboard_enabled") is not None else False),
        ),
        dashboard_host=os.getenv("FLOW_AGENT_CHANNEL_DASHBOARD_HOST", "")
        or str(_deep_get(external_config, "channels", "dashboard_host") or "127.0.0.1"),
        dashboard_port=int(
            os.getenv("FLOW_AGENT_CHANNEL_DASHBOARD_PORT", "")
            or str(_deep_get(external_config, "channels", "dashboard_port") or "8787")
        ),
    )
    jobs = JobsSettings(
        max_async_queue=max(
            1,
            int(
                os.getenv("FLOW_AGENT_JOBS_MAX_ASYNC_QUEUE", "")
                or str(_deep_get(external_config, "jobs", "max_async_queue") or "64")
            ),
        ),
        timeout_seconds=max(
            0.1,
            float(
                os.getenv("FLOW_AGENT_JOBS_TIMEOUT_SECONDS", "")
                or str(_deep_get(external_config, "jobs", "timeout_seconds") or "30")
            ),
        ),
    )
    subagent = SubagentSettings(
        max_concurrency=max(
            1,
            int(
                os.getenv("FLOW_AGENT_SUBAGENT_MAX_CONCURRENCY", "")
                or str(_deep_get(external_config, "subagent", "max_concurrency") or "2")
            ),
        ),
        tasks_file=os.getenv("FLOW_AGENT_SUBAGENT_TASKS_FILE", "")
        or str(_deep_get(external_config, "subagent", "tasks_file") or str(project_root / ".flow_agent" / "subagent_tasks.jsonl")),
    )
    governance = ConfigGovernanceSettings(
        config_version=os.getenv("FLOW_AGENT_CONFIG_VERSION", "")
        or str(_deep_get(external_config, "governance", "config_version") or "v1"),
        profile=os.getenv("FLOW_AGENT_PROFILE", "")
        or str(_deep_get(external_config, "governance", "profile") or "dev"),
        external_config_path=external_path or None,
    )
    mcp_enabled = os.getenv("FLOW_AGENT_MCP_ENABLED", "false").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    mcp_servers_raw = _split_csv(os.getenv("FLOW_AGENT_MCP_SERVERS", ""))
    mcp_servers = [
        MCPServerSettings(name=name, enabled=True, tools=[])
        for name in mcp_servers_raw
    ]
    mcp = MCPSettings(
        enabled=mcp_enabled,
        servers=mcp_servers,
    )

    return Settings(
        model=model,
        storage=storage,
        logging=logging,
        session=session,
        tooling=tooling,
        retrieval=retrieval,
        observe=observe,
        memory_policy=memory_policy,
        proactive=proactive,
        channels=channels,
        jobs=jobs,
        subagent=subagent,
        governance=governance,
        mcp=mcp,
    )
