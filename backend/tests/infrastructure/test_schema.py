from copy import deepcopy

import pytest
from pydantic import ValidationError

from infra.config import AppConfig


def minimal_config() -> dict[str, object]:
    return {"llm": {"main": {"model": "model-main", "api_key": "secret"}}}


def complete_config() -> dict[str, object]:
    return {
        "llm": {
            "main": {
                "model": "model-main",
                "api_key": "main-secret",
                "base_url": "https://main.example/v1",
                "system_prompt": "系统提示词",
                "enable_thinking": False,
            },
            "fast": {
                "model": "model-fast",
                "api_key": "fast-secret",
                "base_url": "https://fast.example/v1",
            },
            "vision": {
                "model": "model-vision",
                "api_key": "vision-secret",
                "base_url": "https://vision.example/v1",
            },
            "fallback_enabled": False,
        },
        "embedding": {
            "provider": "provider",
            "model": "embedding-model",
            "api_key": "embedding-secret",
            "base_url": "https://embedding.example/v1",
        },
        "storage": {
            "memory_db_path": "var/memory.db",
            "outbox_recovery_window_seconds": 12.0,
            "outbox_recovery_limit": 12,
        },
        "logging": {"level": "DEBUG"},
        "session": {
            "default_session_id": "session",
            "max_history_messages": 60,
            "cache_size": 8,
            "undo_enabled": False,
            "tool_result_max_chars": 2000,
        },
        "tooling": {
            "enabled": False,
            "max_tool_steps": 3,
            "tool_selection_max": 4,
        },
        "mcp": {
            "enabled": False,
            "startup_timeout_seconds": 2.0,
            "call_timeout_seconds": 3.0,
        },
        "retrieval": {"enabled": False, "max_items": 4, "min_score": 0.4},
        "observe": {"enabled": False, "trace_path": "var/trace.jsonl"},
        "memory_policy": {"enabled": False, "max_messages": 20, "dedupe": False},
        "memory": {
            "enabled": False,
            "consolidation_min_new_messages": 3,
            "recent_turns_limit": 6,
            "optimizer_enabled": False,
            "optimizer_interval_seconds": 120,
        },
        "proactive": {
            "enabled": True,
            "max_per_day": 3,
            "min_interval": 10.0,
            "max_interval": 20.0,
            "cooldown": 5.0,
            "judge_model": "judge-model",
            "hawkes_enabled": False,
            "hawkes_base_intensity": 1.0,
            "hawkes_excitation_alpha": 0.2,
            "hawkes_decay_beta": 0.3,
            "hawkes_time_constant": 5.0,
            "telegram_target_user_id": "10001",
            "idle_enabled": True,
            "idle_threshold_minutes": 30.0,
            "interest_topics": ["Python", "Agent"],
            "state_path": "var/proactive.db",
            "trace_path": "var/proactive.jsonl",
        },
        "drift": {
            "enabled": False,
            "data_dir": "var/drift",
            "min_interval_hours": 2.0,
            "max_steps": 8,
        },
        "channels": {
            "dashboard_enabled": True,
            "dashboard_host": "0.0.0.0",
            "dashboard_port": 9901,
            "http_enabled": True,
            "http_host": "0.0.0.0",
            "http_port": 8788,
            "telegram_enabled": True,
            "telegram_bot_token": "bot-secret",
            "telegram_allowed_users": "10001,10002",
            "telegram_allowed_groups": "20001,20002",
        },
        "jobs": {
            "max_async_queue": 20,
            "max_async_workers": 3,
            "timeout_seconds": 12.0,
        },
        "subagent": {"max_concurrency": 3, "tasks_file": "var/tasks.jsonl"},
        "persona": {
            "name": "助手",
            "passive_tone": "简洁",
            "proactive_tone": "友好",
            "style": "结构化",
        },
        "prompt_budget": {
            "max_chars": 9000,
            "history_chars": 3500,
            "memory_chars": 1800,
            "tool_trace_chars": 1200,
        },
        "delegation_policy": {"max_local_chars": 600, "enabled": False},
    }


def test_config_is_frozen_and_rejects_unknown_fields():
    config = AppConfig.model_validate(minimal_config())
    with pytest.raises(ValidationError):
        config.jobs.max_async_workers = 8

    raw = minimal_config()
    raw["unknown"] = True
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_enabled_telegram_requires_credentials():
    raw = minimal_config()
    raw["channels"] = {"telegram_enabled": True}

    with pytest.raises(ValidationError, match="Telegram"):
        AppConfig.model_validate(raw)


def test_enabled_proactive_requires_target_and_ordered_intervals():
    missing_target = minimal_config()
    missing_target["proactive"] = {"enabled": True}
    with pytest.raises(ValidationError, match="主动推送"):
        AppConfig.model_validate(missing_target)

    reversed_intervals = minimal_config()
    reversed_intervals["proactive"] = {
        "min_interval": 20.0,
        "max_interval": 10.0,
    }
    with pytest.raises(ValidationError, match="最小间隔"):
        AppConfig.model_validate(reversed_intervals)


def test_complete_product_configuration_is_retained():
    raw = complete_config()

    config = AppConfig.model_validate(deepcopy(raw))

    assert config.llm.fast is not None
    assert config.llm.vision is not None
    assert config.memory.optimizer_interval_seconds == 120
    assert config.proactive.interest_topics == ("Python", "Agent")
    assert config.channels.telegram_allowed_groups == "20001,20002"
    assert config.prompt_budget.tool_trace_chars == 1200
    assert config.delegation_policy.enabled is False
