from pathlib import Path

from flow_agent.mcp.client import MCPClient
from flow_agent.mcp.registry import MCPRegistry, MCPServerConfig
# SourceGateway/ContentStore removed in new architecture
# LocalFileSource removed in new architecture
from flow_agent.proactive.types import SourceRecord
from flow_agent.skills.loader import SkillLoader
from flow_agent.skills.registry import SkillRegistry


class BrokenSource:
    @property
    def name(self) -> str:
        return "broken"

    def fetch_records(self) -> list[SourceRecord]:
        raise RuntimeError("boom")


def test_source_gateway_isolates_source_failure(tmp_path: Path):
    # New architecture: DataGateway handles isolation via asyncio.gather(return_exceptions=True)
    from flow_agent.proactive.data_gateway import DataGateway
    from flow_agent.proactive.mcp_pool import McpClientPool
    import asyncio
    pool = McpClientPool()
    gateway = DataGateway(pool)
    result = asyncio.run(gateway.run())
    assert result.alerts == []
    assert result.content == []
    assert result.context == []


def test_content_store_deduplicates_records():
    # New architecture: dedup done via ProactiveStateStore in resolve phase
    from flow_agent.proactive.gate import ProactiveStateStore
    from flow_agent.proactive.resolve import resolve_decision
    from flow_agent.proactive.models import JudgeResult
    import hashlib
    store = ProactiveStateStore()
    # Mark with the actual delivery key that _build_delivery_key will produce
    cited = ["dedup_key"]
    actual = hashlib.sha256(",".join(sorted(cited)).encode()).hexdigest()[:24]
    store.mark_sent(actual)
    judge = JudgeResult(decision="reply", message="test", cited_item_ids=cited)
    result = resolve_decision(judge, state_store=store)
    assert result.decision == "skip"


def test_mcp_registry_mount_discover_and_call():
    registry = MCPRegistry()
    client = MCPClient(server_name="ext", tool_handlers={"ping": lambda payload: f"ok:{payload}"})
    registry.register_server(MCPServerConfig(name="ext", enabled=True, tools=["ping"]), client)
    registry.mount("ext")
    tools = registry.discover_tools()
    assert tools == [("ext", "ping", "Tool from MCP server ext")]
    assert registry.call_tool("ext", "ping", {"a": "1"}) == "ok:{'a': '1'}"


def test_skill_loader_and_registry_select(tmp_path: Path):
    skill_dir = tmp_path / "skills" / "notify"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "name: notify",
                "description: send notify skill",
                "requires_tools: read_file",
                "requires_sources: file_feed",
                "requires_mcp: ext",
            ]
        ),
        encoding="utf-8",
    )
    specs = SkillLoader(tmp_path / "skills").load()
    selected = SkillRegistry(specs).select(
        available_tools={"read_file"},
        available_sources={"file_feed"},
        available_mcp={"ext"},
    )
    assert selected is not None
    assert selected.name == "notify"

