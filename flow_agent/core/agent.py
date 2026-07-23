from typing import Any

from flow_agent.behavior.persona import PersonaResolver
from flow_agent.config.settings import Settings
from flow_agent.core.context import ConversationContext
from flow_agent.core.models import AgentResponse
from flow_agent.llm.client import LLMClient
from flow_agent.llm.assembler import PromptAssembler
from flow_agent.llm.router import LLMRouter


class Agent:
    def __init__(
        self,
        settings: Settings,
        llm_client: LLMClient,
        context: ConversationContext,
        session_id: str = "default",
        llm_router: LLMRouter | None = None,
        prompt_assembler: PromptAssembler | None = None,
        persona_resolver: PersonaResolver | None = None,
    ) -> None:
        self.settings = settings
        self.llm_client = llm_client
        self.context = context
        self.session_id = session_id
        self.llm_router = llm_router
        self.prompt_assembler = prompt_assembler
        self.persona_resolver = persona_resolver

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
    ) -> list[dict[str, str]]:
        history = self.context.get_history(self.session_id)
        if self.prompt_assembler is None:
            messages: list[dict[str, str]] = [{"role": "system", "content": self.settings.system_prompt}]
            if persona_block:
                messages.append({"role": "system", "content": persona_block})
            if history:
                messages.extend(history)
            if memory_block:
                messages.append({"role": "system", "content": memory_block})
            if retrieval_block:
                messages.append({"role": "system", "content": retrieval_block})
            messages.append({"role": "user", "content": user_input})
            return messages
        return self.prompt_assembler.assemble(
            system_block=self.settings.system_prompt,
            persona_block=persona_block,
            history=history,
            user_input=user_input,
            memory_block=memory_block,
            retrieval_block=retrieval_block,
            tool_instructions=tool_instructions,
            runtime_block=runtime_block,
        )

    def generate_from_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
        if self.llm_router is not None:
            return self.llm_router.generate_main(messages, tools=tools)
        return self.llm_client.generate(messages, tools=tools)

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
    ) -> None:
        """原子提交一轮对话，避免恢复时只看到单侧消息。"""

        self.context.append_turn(
            self.session_id,
            user_input,
            assistant_output,
            assistant_tool_chain=assistant_tool_chain,
        )
