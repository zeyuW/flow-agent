# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Run all tests
PYTHONPATH=. pytest -q

# Run a single test file
PYTHONPATH=. pytest -q tests/test_pipeline.py

# Run a single test function
PYTHONPATH=. pytest -q tests/test_pipeline.py::test_prepare_context

# Type check
pyright flow_agent/

# Format
black flow_agent/ tests/
```

Python 3.10+ required. The venv is at `.venv/`. No Makefile — all commands go through `pytest`/`pyright`/`black` directly.

## Architecture

**flow-agent** is a lightweight agent runtime platform, not a simple chat wrapper. It supports passive (reply-to-message) and proactive (timer-driven) agent behavior, plus background jobs, subagent delegation, and an extension ecosystem (skills/plugins/marketplace).

### The two-bus architecture (stage21)

The most critical architectural decision: **MessageBus and EventBus are completely independent**. This separation was introduced to decouple message transport from lifecycle event notification.

```
Channel (CLI/HTTP/QQ)
  │
  ├─ inbound ──→ MessageBus.publish_inbound()
  │                │
  │                ▼
  │              AgentLoop.consume (async, per-session tasks)
  │                │
  │                ▼
  │              PassiveTurnPipeline.process()  ─── 6 phases
  │                │
  │                ├── EventBus.publish(TurnCommitted)  ← ① fanout FIRST
  │                │      ▼
  │                │    [memory, dashboard, plugins, …] — all subscribers notified
  │                │
  │                └── OutboundPort.send(OutboundDispatch)  ← ② send SECOND
  │                       │
  │                       ▼
  │                     MessageBus outbound queue → dispatch → channel
  │
  └─ outbound ─── MessageBus.subscribe_outbound(channel, callback)
```

| Bus          | Pattern                           | Purpose                    | Key types                                           |
| ------------ | --------------------------------- | -------------------------- | --------------------------------------------------- |
| `MessageBus` | Queue + per-channel subscribers   | Message transport (in/out) | `InboundQueue`, `OutboundQueue`, `OutboundDispatch` |
| `EventBus`   | Pub/sub fanout to all subscribers | Lifecycle events           | `Event`, `TurnCommitted`                            |

**Why the order matters:** AfterTurn broadcasts `TurnCommitted` via EventBus *before* dispatching the reply via OutboundPort. If the reply were sent first and failed, subscribers would have inconsistent state.

### The six-phase passive turn pipeline

```
TurnStarted → BeforeTurn → BeforeReasoning → PromptRender → Reasoner → AfterReasoning → AfterTurn
```

- `PromptRender` assembles persona block, memory block, retrieval block, and tool instructions into the final messages array
- `Reasoner` runs the tool-calling loop (up to `max_tool_steps` iterations)
- `AfterTurn` does two things in strict order: ① EventBus fanout → ② OutboundPort send
- `PhaseModule` plugins can hook into `on_turn_started`, `on_before_reasoning`, `on_prompt_render`, `on_after_reasoning`, `on_after_turn`

### AgentLoop concurrency model

`AgentLoop` runs as an async consumer on the MessageBus inbound queue. For each inbound message, it spawns an independent `asyncio.create_task()` — one session's long reasoning never blocks another session's response. `ProcessingState` prevents the same session from being processed concurrently.

### Proactive tick pipeline

```
IntervalScheduler → SourceGateway (LocalFile, Todo, RSS, Web, MemoryFollowUp)
  → CandidateRanker → DecisionLayer → PreGate → ProactiveJudge → DriftRunner → send
```

Configured via `ProactiveSettings` in `.env`; disabled by default (`enabled: False`).

### Key subsystems

| Directory                           | Responsibility                                                                        |
| ----------------------------------- | ------------------------------------------------------------------------------------- |
| `core/`                             | Turn pipeline, agent loop, orchestrator, agent, delegation, phase modules             |
| `messaging/`                        | MessageBus (inbound/outbound queues) + EventBus (fanout pub/sub)                      |
| `proactive/`                        | Scheduled tick → source gateway → candidate rank → judge → send/drift                 |
| `memory/`                           | Session history (SQLite), keyword retrieval, organizer, consolidation, profiles       |
| `background/`                       | Async job runtime: registry, workers, reentry guard                                   |
| `subagent/`                         | Task lifecycle: create → run → complete/summarize, concurrency-limited                |
| `channels/`                         | CLI, HTTP, QQ (NapCat) channels; `ChannelManager` handles lifecycle/metrics/audit     |
| `dashboard/`                        | In-memory event store + HTTP API (`/snapshot`, `/runtime`)                            |
| `observe/`                          | Unified event envelope with trace_id/correlation_id/parent_id                         |
| `runtime/`                          | Workspace init, `RuntimeService` (unified lifecycle), retry/fallback                  |
| `security/`                         | Auth, permissions, command governance                                                 |
| `guard/`                            | Tool allow/deny, subagent concurrency, background reentry, source isolation           |
| `skills/` `plugins/` `marketplace/` | Extension ecosystem: scan, install, enable/disable, local index                       |
| `config/`                           | Pydantic settings schema, lazy singleton via `settings` proxy, `.env` + external TOML |
| `tools/`                            | Tool protocol, registry, built-in tools, OpenAI function-schema export                |
| `mcp/`                              | MCP server config, tool discovery, adapter                                            |
| `llm/`                              | OpenAI client, router (main/fast model), prompt assembler with budget control         |
| `behavior/`                         | Persona resolver (tone/style by channel and proactive/passive mode)                   |
| `ops/`                              | Audit log, usage metrics, incident records                                            |
| `facade/`                           | Stable internal API boundaries (Memory, Proactive, Background, etc.)                  |
| `eval/`                             | Scenario runner, baseline regression, assertions                                      |

### Assembly point

`flow_agent/app/bootstrap.py` is the most critical file — it wires everything together: creates `MessageBus` + `EventBus`, builds the `PassiveTurnPipeline`, creates `AgentLoop`, assembles `ProactiveRuntime`, `BackgroundRuntime`, `SubagentRuntime`, `DashboardServer`, and returns the full `RuntimeService`. Start there when tracing how anything connects.

### CLI entry points

```
flow-agent init [--workspace .]     # initialize workspace
flow-agent run                       # interactive agent
flow-agent dashboard                 # start dashboard HTTP server
flow-agent runtime snapshot|health|reload|restart|stop|start
flow-agent channels list
flow-agent sources list
flow-agent skills list|install|enable|disable
flow-agent plugins list|install|uninstall|enable|disable
flow-agent marketplace list|rebuild
flow-agent jobs list
```

### Configuration

- `.env` is the primary config source
- Optional external config: `FLOW_AGENT_CONFIG_FILE=/path/to/config.toml`
- Settings schema: `flow_agent/config/settings.py` (Pydantic `Settings` model, lazy singleton via `settings` proxy)
- `settings.get()` returns the cached `Settings` instance; `settings.reload()` forces re-read

### Workspace layout

`flow-agent init` creates a hidden `.flow/` directory:

```
<workspace>/
  .flow/
    config/flow-agent.toml
    data/memory.db, marketplace-index.json
    skills/  plugins/  sources/
    sessions/subagent_tasks.jsonl
    logs/trace.jsonl, audit.jsonl
    .workspace
```

### Testing patterns

- Tests use `ScriptedLLMClient` (returns scripted responses without real API calls) and `FakeTool` for deterministic pipeline tests
- Stage-based tests (`test_stage12_*.py`, `test_stage19_*.py`) cover end-to-end capabilities across subsystems
- Feature-specific tests (`test_pipeline.py`, `test_message_bus_architecture.py`) cover individual modules
- All tests expect `PYTHONPATH=.` — there is no `conftest.py` at the repo root

### Development conventions

1. **Coding order**: Define interface/base class first → then implementation → then wire into entry points
2. **Directory discipline**: core logic in `core/`, memory in `memory/`, tools in `tools/`, config in `config/`, infra in `infra/`
3. All classes and key functions must have Chinese docstrings
4. Must add logging for traceability
5. Must handle exceptions — no unprotected crashes in main flows
6. All changes must include tests
