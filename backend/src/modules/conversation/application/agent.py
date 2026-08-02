import base64
from pathlib import Path
from typing import Any

from modules.capabilities.behavior.persona import PersonaResolver
from modules.conversation.application.models import AgentResponse
from modules.conversation.application.ports import ConversationHistory
from modules.capabilities.llm.client import LLMClient
from modules.capabilities.llm.assembler import PromptAssembler
from modules.capabilities.llm.router import LLMRouter


class Agent:
    def __init__(
        self,
        system_prompt: str,
        llm_client: LLMClient,
        context: ConversationHistory,
        session_id: str = "default",
        llm_router: LLMRouter | None = None,
        prompt_assembler: PromptAssembler | None = None,
        persona_resolver: PersonaResolver | None = None,
        vision_client: LLMClient | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.llm_client = llm_client
        self.context = context
        self.session_id = session_id
        self.llm_router = llm_router
        self.prompt_assembler = prompt_assembler
        self.persona_resolver = persona_resolver
        self.vision_client = vision_client

    def set_session(self, session_id: str) -> None:
        self.session_id = session_id

    def run(self, user_input: str) -> AgentResponse:
        messages = self.build_turn_messages(user_input=user_input)
        result = self.llm_client.generate(messages)

        self.context.append_user_message(self.session_id, user_input)
        self.context.append_assistant_message(self.session_id, result.content)

        return AgentResponse(content=result.content)

    def build_turn_messages(
        self,
        user_input: str,
        *,
        persona_block: str = "",
        memory_block: str = "",
        retrieval_block: str = "",
        tool_instructions: str = "",
        runtime_block: str = "",
        session_id: str | None = None,
        media: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        history = self.context.get_history(session_id or self.session_id)
        if self.prompt_assembler is None:
            messages: list[dict[str, str]] = [
                {"role": "system", "content": self.system_prompt}
            ]
            if persona_block:
                messages.append({"role": "system", "content": persona_block})
            if history:
                messages.extend(history)
            if memory_block:
                messages.append({"role": "system", "content": memory_block})
            if retrieval_block:
                messages.append({"role": "system", "content": retrieval_block})
            messages.append(_user_message_with_media(user_input, media or []))
            return messages
        messages = self.prompt_assembler.assemble(
            system_block=self.system_prompt,
            persona_block=persona_block,
            history=history,
            user_input=user_input,
            memory_block=memory_block,
            retrieval_block=retrieval_block,
            tool_instructions=tool_instructions,
            runtime_block=runtime_block,
        )
        if media:
            messages[-1] = _user_message_with_media(user_input, media)
        return messages

    def generate_from_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
        if _contains_image(messages):
            if self.vision_client is None:
                raise RuntimeError("未配置视觉模型，无法识别图片")
            return self.vision_client.generate(messages, tools=tools)
        if self.llm_router is not None:
            return self.llm_router.generate_main(messages, tools=tools)
        return self.llm_client.generate(messages, tools=tools)

    async def generate_from_messages_async(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
        """异步生成模型结果，禁止在被动回合中退回同步网络调用。"""

        if _contains_image(messages):
            generate_async = getattr(self.vision_client, "generate_async", None)
            if not callable(generate_async):
                raise RuntimeError("未配置支持异步调用的视觉模型")
            return await generate_async(messages, tools=tools)
        if self.llm_router is not None:
            return await self.llm_router.generate_main_async(messages, tools=tools)
        generate_async = getattr(self.llm_client, "generate_async", None)
        if not callable(generate_async):
            raise RuntimeError("当前模型客户端不支持异步生成")
        return await generate_async(messages, tools=tools)

    def fast_generate_from_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
        if self.llm_router is not None:
            return self.llm_router.generate_fast(messages, tools=tools)
        return self.llm_client.generate(messages, tools=tools)

    def commit_turn(
        self,
        user_input: str,
        assistant_output: str,
        *,
        assistant_tool_chain: list | None = None,
        session_id: str | None = None,
    ) -> None:
        """原子提交一轮对话，避免恢复时只看到单侧消息。"""

        self.context.append_turn(
            session_id or self.session_id,
            user_input,
            assistant_output,
            assistant_tool_chain=assistant_tool_chain,
        )


def _user_message_with_media(text: str, media: list[str]) -> dict[str, Any]:
    """把受控本地图片编码为兼容视觉模型的 data URL 内容块。"""

    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for raw_path in media[:4]:
        path = Path(raw_path)
        data = path.read_bytes()
        if not data or len(data) > 20 * 1024 * 1024:
            continue
        mime_type = _detect_image_mime(data)
        if mime_type is None:
            continue
        encoded = base64.b64encode(data).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
        })
    return {"role": "user", "content": content if len(content) > 1 else text}


def _detect_image_mime(data: bytes) -> str | None:
    """以文件签名而非路径后缀决定传给视觉模型的图片 MIME。"""

    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _contains_image(messages: list[dict[str, Any]]) -> bool:
    """仅在用户消息确实包含图片块时切换到独立视觉模型。"""

    return any(
        isinstance(message.get("content"), list)
        and any(item.get("type") == "image_url" for item in message["content"])
        for message in messages
    )
