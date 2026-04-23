from dataclasses import dataclass


@dataclass(slots=True)
class PersonaProfile:
    """Agent persona profile and style defaults."""

    name: str = "FlowAgent"
    tone_passive: str = "professional, concise, helpful"
    tone_proactive: str = "friendly, brief, actionable"
    default_style: str = "structured"


class PersonaResolver:
    """Resolve channel-aware persona prompt block."""

    def __init__(self, profile: PersonaProfile) -> None:
        self.profile = profile

    def render_block(self, *, channel: str, proactive_mode: bool) -> str:
        tone = self.profile.tone_proactive if proactive_mode else self.profile.tone_passive
        return (
            f"Persona: {self.profile.name}\n"
            f"Channel: {channel}\n"
            f"Tone: {tone}\n"
            f"Style: {self.profile.default_style}"
        )

