"""Tests for ProactiveLoop gate checks and state store."""

import time

from modules.proactive.infra.gate import ProactiveStateStore, AnyActionGate, check_gate


def test_gate_blocked_when_no_target():
    result = check_gate(chat_id="", is_busy=False)
    assert result.passed is False
    assert result.reason == "no_target"


def test_gate_blocked_when_busy():
    result = check_gate(chat_id="user1", is_busy=True)
    assert result.passed is False
    assert result.reason == "passive_busy"


def test_gate_blocked_by_cooldown():
    store = ProactiveStateStore()
    store.mark_sent("key1")
    result = check_gate(
        chat_id="user1",
        state_store=store,
        cooldown=9999.0,
    )
    assert result.passed is False
    assert result.reason == "cooldown"


def test_gate_passed_when_all_clear():
    store = ProactiveStateStore()
    any_action = AnyActionGate(max_per_day=100)
    result = check_gate(
        chat_id="user1",
        state_store=store,
        any_action=any_action,
        cooldown=0,
        base_score=0.5,
    )
    assert result.passed is True
    assert result.reason == "ok"
    assert result.next_interval > 0


def test_state_store_daily_count():
    store = ProactiveStateStore()
    store._day_start = 0
    assert store.daily_count == 0
    store.mark_sent("key1")
    assert store.daily_count == 1
    # Simulate day change
    store._day_start = time.time() - 86401
    assert store.daily_count == 0


def test_any_action_daily_limit():
    store = ProactiveStateStore()
    gate = AnyActionGate(max_per_day=2, min_interval=0.0)
    assert gate.should_act(store, 1.0) is True
    store.mark_sent("k1")
    assert gate.should_act(store, 1.0) is True
    store.mark_sent("k2")
    assert gate.should_act(store, 1.0) is False
