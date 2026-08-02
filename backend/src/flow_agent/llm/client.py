"""大语言模型客户端的旧路径转发层。"""

from modules.capabilities.llm import client as _client
from modules.capabilities.llm.client import (
    LLMClient,
    LLMResult,
    LLMToolCall,
    FakeLLMClient,
)

OpenAI = _client.OpenAI
AsyncOpenAI = _client.AsyncOpenAI


class OpenAILLMClient(_client.OpenAILLMClient):
    """兼容旧入口的客户端，允许旧测试替换 SDK 构造器。"""

    def __init__(self, config):
        original_openai = _client.OpenAI
        original_async_openai = _client.AsyncOpenAI
        _client.OpenAI = OpenAI
        _client.AsyncOpenAI = AsyncOpenAI
        try:
            super().__init__(config)
        finally:
            _client.OpenAI = original_openai
            _client.AsyncOpenAI = original_async_openai


__all__ = [
    "AsyncOpenAI",
    "FakeLLMClient",
    "LLMClient",
    "LLMResult",
    "LLMToolCall",
    "OpenAI",
    "OpenAILLMClient",
]
