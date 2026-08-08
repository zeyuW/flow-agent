from types import SimpleNamespace

from application.capabilities.llm.client import OpenAILLMClient


def _chunk(*, content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def test_streaming_client_reassembles_tool_call_arguments():
    chunks = [
        _chunk(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id="call-1",
                    function=SimpleNamespace(name="recall_memory", arguments='{"que'),
                )
            ]
        ),
        _chunk(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id=None,
                    function=SimpleNamespace(name=None, arguments='ry":"偏好"}'),
                )
            ]
        ),
    ]

    class Completions:
        def create(self, **kwargs):
            assert kwargs["stream"] is True
            return iter(chunks)

    client = OpenAILLMClient.__new__(OpenAILLMClient)
    client.model = "test-model"
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions()),
    )

    result = client.generate_stream(
        messages=[{"role": "user", "content": "请回忆偏好"}],
        tools=[{"type": "function"}],
    )

    assert result.content == ""
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call-1"
    assert result.tool_calls[0].name == "recall_memory"
    assert result.tool_calls[0].arguments == {"query": "偏好"}


def test_tool_argument_parser_preserves_json_value_types():
    client = OpenAILLMClient.__new__(OpenAILLMClient)

    arguments = client._parse_tool_arguments(
        '{"query":"偏好","max_items":10,"enabled":true,"tags":["ai"]}'
    )

    assert arguments == {
        "query": "偏好",
        "max_items": 10,
        "enabled": True,
        "tags": ["ai"],
    }
