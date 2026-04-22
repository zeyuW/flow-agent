import os
from pathlib import Path

from dotenv import load_dotenv

from flow_agent.config.settings import (
    LoggingSettings,
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
    def _split_csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

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
        memory_db_path=os.getenv(
            "FLOW_AGENT_MEMORY_DB_PATH",
            str(project_root / ".flow_agent" / "memory.db"),
        ),
    )
    logging = LoggingSettings(
        level=os.getenv("FLOW_AGENT_LOG_LEVEL", "INFO"),
    )
    session = SessionSettings(
        default_session_id=os.getenv("FLOW_AGENT_DEFAULT_SESSION", "default"),
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
        mcp=mcp,
    )
