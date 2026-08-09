from application.capabilities.behavior.persona import PersonaProfile, PersonaResolver
from application.agent.domain.policies import DelegationPolicy
from application.capabilities.llm.assembler import PromptAssembler, PromptBudget
from application.capabilities.llm.router import LLMRouter


class FakeResult:
    def __init__(self, content: str) -> None:
        self.content = content


class MainClient:
    def generate(self, messages, tools=None):
        return FakeResult(content="main")


class FastClient:
    def generate(self, messages, tools=None):
        return FakeResult(content="fast")


def test_persona_channel_aware_block():
    resolver = PersonaResolver(
        PersonaProfile(name="A", tone_passive="p", tone_proactive="q", default_style="s")
    )
    passive = resolver.render_block(channel="cli", proactive_mode=False)
    proactive = resolver.render_block(channel="proactive", proactive_mode=True)
    assert "Tone: p" in passive
    assert "Tone: q" in proactive


def test_prompt_assembler_budget_trim():
    assembler = PromptAssembler(PromptBudget(max_chars=120, history_chars=40, memory_chars=20))
    messages = assembler.assemble(
        system_block="sys",
        persona_block="persona",
        history=[{"role": "user", "content": "x" * 30}, {"role": "assistant", "content": "y" * 30}],
        user_input="hello",
        memory_block="m" * 200,
    )
    total = sum(len(m["content"]) for m in messages)
    assert total <= 200  # allow some trim marker overhead


def test_llm_router_main_fast():
    router = LLMRouter(main_client=MainClient(), fast_client=FastClient())
    assert router.generate_main([{"role": "user", "content": "1"}]).content == "main"
    assert router.generate_fast([{"role": "user", "content": "2"}]).content == "fast"


def test_delegation_policy_actions():
    policy = DelegationPolicy(max_local_chars=10)
    assert policy.decide(user_input="普通问题", tool_step_budget=5).action == "handle_locally"
    assert policy.decide(user_input="这是一个很长很长很长的请求", tool_step_budget=5).action == "background_job"
    assert policy.decide(user_input="请委派给subagent处理", tool_step_budget=5).action == "spawn_subagent"
    assert policy.decide(user_input="危险操作", tool_step_budget=5).action == "reject"

