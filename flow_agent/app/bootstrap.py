from pathlib import Path

from flow_agent.config.loader import load_settings
from flow_agent.mcp.client import MCPClient
from flow_agent.mcp.registry import MCPRegistry, MCPServerConfig
from flow_agent.mcp.tool_adapter import MCPToolAdapter
from flow_agent.core.agent import Agent
from flow_agent.core.context import ConversationContext
from flow_agent.core.orchestrator import Orchestrator
from flow_agent.infra.trace import TraceRecorder
from flow_agent.llm.client import OpenAILLMClient
from flow_agent.memory.organizer import SimpleMemoryOrganizer
from flow_agent.memory.retriever import KeywordMemoryRetriever
from flow_agent.memory.store import SQLiteMessageStore
from flow_agent.proactive.runtime import ProactiveRuntime
from flow_agent.proactive.runtime import IntervalScheduler
from flow_agent.proactive.sources import (
    LocalFileSource,
    LocalTodoSource,
    MemoryFollowUpSource,
    RSSFeedSource,
    WebSnapshotSource,
)
from flow_agent.proactive.pipeline import (
    CandidateRanker,
    ContentStore,
    DecisionLayer,
    DriftRunner,
    PreGate,
    ProactiveTickRunner,
    SourceGateway,
)
from flow_agent.proactive.store import SQLiteProactiveSentStore
from flow_agent.skills.loader import SkillLoader
from flow_agent.skills.registry import SkillRegistry
from flow_agent.tools.filesystem import ReadFileTool
from flow_agent.tools.registry import ToolRegistry

'''
负责组装agent
1、加载配置
2、创建上下文
3、创建llm客户端
4、组装智能体
5、将智能体交给总指挥
'''
# 创建总指挥
def create_orchestrator() -> Orchestrator:
    # 加载配置
    settings = load_settings()
    # 创建消息存储
    message_store = SQLiteMessageStore(Path(settings.storage.memory_db_path))
    # 创建上下文
    context = ConversationContext(store=message_store)
    # 创建记忆检索器
    retriever = KeywordMemoryRetriever(store=message_store) if settings.retrieval.enabled else None
    # 创建记忆整理器
    organizer = (
        SimpleMemoryOrganizer(
            store=message_store,
            max_messages=settings.memory_policy.max_messages,
            dedupe=settings.memory_policy.dedupe,
        )
        if settings.memory_policy.enabled
        else None
    )
    # 创建事件记录器
    recorder = (
        TraceRecorder(path=Path(settings.observe.trace_path))
        if settings.observe.enabled
        else None
    )
    # 创建LLM客户端
    llm_client = OpenAILLMClient(settings)
    # 创建工具注册表
    tool_registry = ToolRegistry()
    if settings.tooling.enabled:
        tool_registry.register(ReadFileTool())
    # 创建MCP注册表
    mcp_registry = _build_mcp_registry(settings)
    # 注册MCP工具
    _register_mcp_tools(tool_registry, mcp_registry)
    # 创建智能体
    agent = Agent(
        settings=settings,
        llm_client=llm_client,
        context=context,
    )
    # 创建总指挥
    return Orchestrator(
        agent=agent,
        tool_registry=tool_registry,
        max_tool_steps=settings.tooling.max_tool_steps,
        retriever=retriever,
        retrieval_max_items=settings.retrieval.max_items,
        recorder=recorder,
        organizer=organizer,
    )

# 创建主动运行时
def create_proactive_runtime() -> ProactiveRuntime:
    # 加载配置
    settings = load_settings()
    # 创建消息存储
    db_path = Path(settings.storage.memory_db_path)
    sent_store = SQLiteProactiveSentStore(db_path=db_path)
    message_store = SQLiteMessageStore(db_path)
    # 创建源
    sources = [
        MemoryFollowUpSource(store=message_store, session_id=settings.session.default_session_id),
        LocalTodoSource(Path(settings.proactive.todo_file)),
        LocalFileSource(Path(settings.proactive.source_file)),
        RSSFeedSource([Path(p) for p in settings.proactive.rss_feed_files or []]),
        WebSnapshotSource([Path(p) for p in settings.proactive.web_snapshot_files or []]),
    ]
    gateway = SourceGateway(sources=sources)
    # 创建事件记录器
    recorder = (
        TraceRecorder(path=Path(settings.observe.trace_path))
        if settings.observe.enabled
        else None
    )
    # 创建MCP注册表
    mcp_registry = _build_mcp_registry(settings)
    # 创建技能加载器
    skill_loader = SkillLoader(Path(settings.proactive.skills_dir))
    # 创建技能注册表
    skill_registry = SkillRegistry(skill_loader.load())
    # 创建工具注册表
    local_tool_registry = ToolRegistry()
    if settings.tooling.enabled:
        local_tool_registry.register(ReadFileTool())
    # 创建预门的作用:
    # 预门(PreGate)用于在发送主动消息前检测冷却时间，防止发送频率过高。
    # 它会检查距离上一次主动消息已过去的时间是否超过cooldown_seconds，若未超时则跳过本轮发送。
    pre_gate = PreGate(
        sent_store=sent_store,
        cooldown_seconds=settings.proactive.cooldown_seconds,
    )
    # 创建主动运行时
    tick_runner = ProactiveTickRunner(
        gate=pre_gate,
        gateway=gateway,
        ranker=CandidateRanker(),
        decision_layer=DecisionLayer(
            min_priority_to_send=settings.proactive.min_priority_to_send
        ),
        drift_runner=DriftRunner(
            Path(settings.proactive.tasks_file),
            skill_registry=skill_registry,
            available_tools=local_tool_registry.list_tool_names(),
            available_sources={source.name for source in sources},
            available_mcp=set(mcp_registry.mounted_servers()),
        ),
        sent_store=sent_store,
        dedup_ttl_seconds=settings.proactive.dedup_ttl_seconds,
        content_store=ContentStore(),
        recorder=recorder,
    )
    # 创建定时器
    scheduler = IntervalScheduler(
        interval_seconds=settings.proactive.interval_seconds,
        task=tick_runner.tick,
    )
    # 创建主动运行时
    return ProactiveRuntime(
        scheduler=scheduler,
        tick_runner=tick_runner,
    )


# 创建MCP注册表
def _build_mcp_registry(settings) -> MCPRegistry:
    # 创建MCP注册表
    mcp_registry = MCPRegistry()
    if not settings.mcp.enabled:
        return mcp_registry
    for server in settings.mcp.servers or []:
        handlers = {
            tool_name: (lambda payload, name=tool_name: f"{name}:{payload}")
            for tool_name in server.tools or []
        }
        client = MCPClient(server_name=server.name, tool_handlers=handlers)
        mcp_registry.register_server(
            MCPServerConfig(name=server.name, enabled=server.enabled, tools=server.tools or []),
            client,
        )
        if server.enabled:
            mcp_registry.mount(server.name)
    return mcp_registry

# 注册MCP工具
def _register_mcp_tools(tool_registry: ToolRegistry, mcp_registry: MCPRegistry) -> None:
    # 注册MCP工具
    for server_name, tool_name, description in mcp_registry.discover_tools():
        # 注册MCP工具
        tool_registry.register(
            MCPToolAdapter(
                server_name=server_name,
                tool_name=tool_name,
                description_text=description,
                registry=mcp_registry,
            )
        )
