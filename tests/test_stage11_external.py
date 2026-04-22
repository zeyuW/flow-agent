from pathlib import Path

from flow_agent.mcp.client import MCPClient
from flow_agent.mcp.registry import MCPRegistry, MCPServerConfig
from flow_agent.proactive.pipeline import ContentStore, SourceGateway
from flow_agent.proactive.sources import LocalFileSource
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
    source_file = tmp_path / "items.txt"
    source_file.write_text("hello world\n", encoding="utf-8")
    gateway = SourceGateway([BrokenSource(), LocalFileSource(source_file)])
    records = gateway.fetch_records()
    assert len(records) == 1
    assert records[0].source == "file_feed"


def test_content_store_deduplicates_records():
    store = ContentStore()
    records = [
        SourceRecord(source="s", title="t", content="a", summary="a", dedup_key="k1"),
        SourceRecord(source="s", title="t", content="a", summary="a", dedup_key="k1"),
    ]
    first = store.ingest(records)
    second = store.ingest(records)
    assert len(first) == 1
    assert len(second) == 0


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

