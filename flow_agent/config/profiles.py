from __future__ import annotations

import os


def apply_profile(profile: str) -> None:
    normalized = profile.strip().lower() or "dev"
    os.environ["FLOW_AGENT_PROFILE"] = normalized
    if normalized == "prod":
        os.environ.setdefault("FLOW_AGENT_CHANNEL_HTTP_ENABLED", "true")
        os.environ.setdefault("FLOW_AGENT_CHANNEL_DASHBOARD_ENABLED", "true")
    elif normalized == "dev":
        os.environ.setdefault("FLOW_AGENT_CHANNEL_HTTP_ENABLED", "false")
        os.environ.setdefault("FLOW_AGENT_CHANNEL_DASHBOARD_ENABLED", "false")
