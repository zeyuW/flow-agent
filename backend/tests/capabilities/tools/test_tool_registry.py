from application.capabilities.tools.base import ToolResult
from application.capabilities.tools.registry import ToolRegistry


class EchoTool:
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo input text"

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        return ToolResult(ok=True, content=tool_input.get("text", ""))


def test_registry_register_and_list_descriptions():
    registry = ToolRegistry()
    registry.register(EchoTool())

    assert registry.list_tool_descriptions() == [
        {"name": "echo", "description": "Echo input text"}
    ]


def test_registry_execute_unknown_tool():
    registry = ToolRegistry()
    result = registry.execute("not_exists", {})

    assert result.ok is False
    assert "Unknown tool: not_exists" in result.content


def test_registry_selects_matching_mcp_tool():
    class SearchTool(EchoTool):
        @property
        def name(self) -> str:
            return "mcp__web__search"

        @property
        def description(self) -> str:
            return "搜索外部网页资料"

    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(SearchTool())

    selected = registry.select_openai_tools("请搜索外部网页资料", max_tools=1)

    assert selected[0]["function"]["name"] == "mcp__web__search"


def test_registry_always_selects_explicitly_named_tool():
    class NamedTool(EchoTool):
        def __init__(self, tool_name: str) -> None:
            self._tool_name = tool_name

        @property
        def name(self) -> str:
            return self._tool_name

    registry = ToolRegistry()
    for index in range(12):
        registry.register(NamedTool(f"generic_{index}"))
    registry.register(NamedTool("runtime_probe"))

    selected = registry.select_openai_tools(
        "请务必调用 runtime_probe 工具",
        max_tools=8,
    )

    names = {item["function"]["name"] for item in selected}
    assert "runtime_probe" in names


def test_registry_selects_core_tools_for_chinese_intents():
    class CoreTool(EchoTool):
        def __init__(self, tool_name: str) -> None:
            self._tool_name = tool_name

        @property
        def name(self) -> str:
            return self._tool_name

    registry = ToolRegistry()
    for index in range(12):
        registry.register(CoreTool(f"generic_{index}"))
    for name in ("read", "write", "edit", "bash"):
        registry.register(CoreTool(name))

    selected = registry.select_openai_tools(
        "写入并编辑文件后执行 git status", max_tools=3
    )

    names = {item["function"]["name"] for item in selected}
    assert {"write", "edit", "bash"} == names
