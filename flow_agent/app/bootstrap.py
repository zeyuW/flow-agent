from pathlib import Path

from flow_agent.config.loader import load_settings
from flow_agent.core.agent import Agent
from flow_agent.core.context import ConversationContext
from flow_agent.core.orchestrator import Orchestrator
from flow_agent.infra.trace import TraceRecorder
from flow_agent.llm.client import OpenAILLMClient
from flow_agent.memory.organizer import SimpleMemoryOrganizer
from flow_agent.memory.retriever import KeywordMemoryRetriever
from flow_agent.memory.store import SQLiteMessageStore
from flow_agent.proactive.gate import SimplePreGate
from flow_agent.proactive.runtime import ProactiveRuntime
from flow_agent.proactive.scheduler import IntervalScheduler
from flow_agent.proactive.source import LocalFileCandidateSource
from flow_agent.proactive.store import SQLiteProactiveSentStore
from flow_agent.proactive.tick import ProactiveTickRunner
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
def create_orchestrator() -> Orchestrator:
    settings = load_settings()
    message_store = SQLiteMessageStore(Path(settings.storage.memory_db_path))
    context = ConversationContext(store=message_store)
    retriever = KeywordMemoryRetriever(store=message_store) if settings.retrieval.enabled else None
    organizer = (
        SimpleMemoryOrganizer(
            store=message_store,
            max_messages=settings.memory_policy.max_messages,
            dedupe=settings.memory_policy.dedupe,
        )
        if settings.memory_policy.enabled
        else None
    )
    recorder = (
        TraceRecorder(path=Path(settings.observe.trace_path))
        if settings.observe.enabled
        else None
    )
    llm_client = OpenAILLMClient(settings)
    tool_registry = ToolRegistry()
    if settings.tooling.enabled:
        tool_registry.register(ReadFileTool())
    agent = Agent(
        settings=settings,
        llm_client=llm_client,
        context=context,
    )

    return Orchestrator(
        agent=agent,
        tool_registry=tool_registry,
        max_tool_steps=settings.tooling.max_tool_steps,
        retriever=retriever,
        retrieval_max_items=settings.retrieval.max_items,
        recorder=recorder,
        organizer=organizer,
    )


def create_proactive_runtime() -> ProactiveRuntime:
    settings = load_settings()
    sent_store = SQLiteProactiveSentStore(Path(settings.storage.memory_db_path))
    source = LocalFileCandidateSource(Path(settings.proactive.source_file))
    recorder = (
        TraceRecorder(path=Path(settings.observe.trace_path))
        if settings.observe.enabled
        else None
    )
    gate = SimplePreGate(
        sent_store=sent_store,
        cooldown_seconds=settings.proactive.cooldown_seconds,
    )
    tick_runner = ProactiveTickRunner(
        gate=gate,
        source=source,
        sent_store=sent_store,
        dedup_ttl_seconds=settings.proactive.dedup_ttl_seconds,
        recorder=recorder,
    )
    scheduler = IntervalScheduler(
        interval_seconds=settings.proactive.interval_seconds,
        task=tick_runner.tick,
    )
    return ProactiveRuntime(
        scheduler=scheduler,
        tick_runner=tick_runner,
    )
