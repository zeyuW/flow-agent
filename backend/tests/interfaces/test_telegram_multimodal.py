from __future__ import annotations

import asyncio
from pathlib import Path

from interfaces.channels.telegram import TelegramChannel
from application.conversation.app.agent import Agent
from application.conversation.app.pipeline import PassiveTurnPipeline
from application.conversation.app.phase import TurnFlow
from application.capabilities.llm.client import LLMResult
from application.capabilities.llm.client import LLMToolCall
from application.capabilities.skills.loader import SkillLoader
from application.capabilities.tools.message_push import MessagePushTool


class _Bus:
    def __init__(self) -> None:
        self.items = []

    def publish_inbound(self, item) -> None:
        self.items.append(item)


class _Context:
    def __init__(self) -> None:
        self.bus = _Bus()


def test_telegram_photo_is_downloaded_and_published_as_media(tmp_path: Path, monkeypatch):
    channel = TelegramChannel("token", attachment_dir=tmp_path)
    channel._context = _Context()

    async def download(file_id: str, *, filename: str) -> str:
        assert file_id == "largest"
        path = tmp_path / filename
        path.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
        return str(path)

    monkeypatch.setattr(channel, "_download_image", download)
    update = {
        "message": {
            "message_id": 7,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "username": "user"},
            "caption": "这是什么？",
            "photo": [{"file_id": "small"}, {"file_id": "largest"}],
        }
    }

    asyncio.run(channel._handle_update(update))

    inbound = channel._context.bus.items[0]
    assert inbound.text == "这是什么？"
    assert inbound.media == [str(tmp_path / "telegram_42_7.png")]


def test_telegram_image_document_is_downloaded_and_published_as_media(
    tmp_path: Path,
    monkeypatch,
):
    channel = TelegramChannel("token", attachment_dir=tmp_path)
    channel._context = _Context()

    async def download(file_id: str, *, filename: str) -> str:
        assert file_id == "document"
        path = tmp_path / filename
        path.write_bytes(b"RIFF\x00\x00\x00\x00WEBPcontent")
        return str(path)

    monkeypatch.setattr(channel, "_download_image", download)
    update = {
        "message": {
            "message_id": 8,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42},
            "document": {
                "file_id": "document",
                "file_name": "original.webp",
                "mime_type": "image/webp",
            },
        }
    }

    asyncio.run(channel._handle_update(update))

    inbound = channel._context.bus.items[0]
    assert inbound.text == "请描述这张图片。"
    assert inbound.media == [str(tmp_path / "telegram_42_8.webp")]


def test_agent_builds_openai_compatible_image_content(tmp_path: Path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
    agent = Agent.__new__(Agent)
    agent.system_prompt = "system"
    agent.context = type("Context", (), {"get_history": lambda *_: []})()
    agent.session_id = "s"
    agent.prompt_assembler = None
    agent.persona_resolver = None

    messages = agent.build_turn_messages("识别图片", media=[str(image)])

    assert messages[-1]["content"][0] == {"type": "text", "text": "识别图片"}
    assert messages[-1]["content"][1]["type"] == "image_url"
    assert messages[-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_telegram_send_image_uploads_local_photo(tmp_path: Path, monkeypatch):
    image = tmp_path / "reply.png"
    image.write_bytes(b"image")
    channel = TelegramChannel("token")
    calls = []

    def upload(chat_id: int, path: Path, caption: str = "") -> dict:
        calls.append((chat_id, path, caption))
        return {"ok": True}

    monkeypatch.setattr(channel, "_post_photo", upload)

    channel.send_image(chat_id="42", path=str(image))

    assert calls == [(42, image, "")]


def test_telegram_send_image_passes_public_url_to_send_photo(monkeypatch):
    channel = TelegramChannel("token")
    calls = []

    def send_url(chat_id: int, url: str, caption: str = "") -> dict:
        calls.append((chat_id, url, caption))
        return {"ok": True}

    monkeypatch.setattr(channel, "_post_photo_url", send_url)

    channel.send_image(chat_id="42", path="https://images.example.test/cat.png")

    assert calls == [(42, "https://images.example.test/cat.png", "")]


def test_message_push_schema_allows_image_only_delivery():
    tool = MessagePushTool()
    delivered = []
    tool.register_channel(
        "telegram",
        send_image=lambda *, chat_id, path: delivered.append((chat_id, path)),
    )

    result = tool.run(
        {
            "channel": "telegram",
            "chat_id": "42",
            "image_path": "https://images.example.test/cat.png",
        }
    )

    assert {"required": ["image_path"]} in tool.input_schema["anyOf"]
    assert result.ok is True
    assert delivered == [("42", "https://images.example.test/cat.png")]


def test_passive_message_push_uses_current_telegram_chat_identity():
    pipeline = PassiveTurnPipeline.__new__(PassiveTurnPipeline)
    flow = TurnFlow(
        user_input="发一张图片",
        session_id="telegram:42",
        channel="telegram",
        trace_id="trace",
        inbound_metadata={"telegram_chat_id": 42},
    )
    tool_call = LLMToolCall(
        id="call",
        name="message_push",
        arguments_json="{}",
        arguments={
            "channel": "other",
            "chat_id": "999",
            "image_path": "https://images.example.test/cat.png",
        },
    )

    tool_input = pipeline._tool_input_for_flow(tool_call, flow)

    assert tool_input["channel"] == "telegram"
    assert tool_input["chat_id"] == "42"


def test_skill_loader_reads_image_capability_requirements(tmp_path: Path):
    skill_dir = tmp_path / "vision" 
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "name: vision\nrequires_vision_model: true\nrequires_image_output: true\n",
        encoding="utf-8",
    )

    skill = SkillLoader(tmp_path).load()[0]

    assert skill.requires_vision_model is True
    assert skill.requires_image_output is True


def test_agent_routes_image_messages_to_configured_vision_client(tmp_path: Path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
    calls: list[str] = []

    class Client:
        def generate(self, messages, tools=None):
            calls.append("vision")
            return LLMResult(content="识别结果")

    agent = Agent.__new__(Agent)
    agent.llm_router = None
    agent.llm_client = object()
    agent.vision_client = Client()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "识别"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
    ]}]

    assert agent.generate_from_messages(messages).content == "识别结果"
    assert calls == ["vision"]
