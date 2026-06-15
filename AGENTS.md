# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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

Python in the venv is already installed at `.venv/`. No Makefile — all commands go through `pytest`/`pyright`/`black` directly.

## Architecture

**flow-agent** is a lightweight agent runtime platform, not a simple chat wrapper. It supports passive (reply-to-message) and proactive (timer-driven) agent behavior, plus background jobs, subagent delegation, and an extension ecosystem (skills/plugins/marketplace).

### Main request flow

```
Channel (CLI/HTTP/QQ)
  → Bootstrap (app/bootstrap.py — wires everything together)
    → Orchestrator.run_turn()
      → TurnPipeline.process_turn()
        → context_prepare() — retrieval, persona, prompt assembly
        → reasoner_run_turn() — delegation decision, then tool loop
        → context_commit() — persist, memory organize
```

### Key subsystems

| Directory | Responsibility |
|-----------|---------------|
| `core/` | Turn pipeline, orchestrator, agent, context store, delegation policy |
| `proactive/` | Scheduled tick → source gateway → candidate rank → judge → send/drift |
| `memory/` | Session history (SQLite), retrieval (keyword-based), organizer, consolidation, profile extraction |
| `background/` | Async job runtime: registry, workers, reentry guard |
| `subagent/` | Task lifecycle: create → run → complete/summarize, concurrency-limited |
| `channels/` | CLI, HTTP, QQ message channels; `ChannelManager` handles lifecycle/metrics/audit |
| `dashboard/` | In-memory event store + HTTP API (`/snapshot`, `/runtime`) |
| `observe/` | Unified event envelope with trace_id/correlation_id/parent_id |
| `runtime/` | Workspace init, `RuntimeService` (unified lifecycle), retry/fallback |
| `security/` | Auth, permissions, command governance |
| `guard/` | Tool allow/deny, subagent concurrency, background reentry, source isolation |
| `skills/` `plugins/` `marketplace/` | Extension ecosystem: scan, install, enable/disable, local index |
| `config/` | Settings schema (Pydantic), multi-source loader (`.env` + external TOML/YAML) |
| `tools/` | Tool protocol, registry, built-in tools, OpenAI function-schema export |
| `mcp/` | MCP server config, tool discovery, adapter |
| `llm/` | Client, router (main/fast model), prompt assembler with budget control |
| `behavior/` | Persona resolver (tone/style by channel and proactive/passive mode) |
| `ops/` | Audit log, usage metrics, incident records |
| `facade/` | Stable internal API boundaries (Memory, Proactive, Background, etc.) |
| `eval/` | Scenario runner, baseline regression, assertions |

### Assembly point

`flow_agent/app/bootstrap.py` is the most critical file for understanding how the system wires together — it creates all runtimes, registers components, and returns the assembled `RuntimeService`. Start there when tracing how anything connects.

### Configuration

- `.env` is the primary config source
- Optional external config: `FLOW_AGENT_CONFIG_FILE=/path/to/config.toml`
- Settings schema: `flow_agent/config/settings.py` (lazy singleton via `settings` proxy)
- Config profiles: `dev.toml` / `prod.toml` in `config/`

### Workspace layout

`flow-agent init` creates a standard workspace with `.workspace` marker file:

```
<workspace>/
  config/flow-agent.toml
  data/memory.db, marketplace-index.json
  skills/  plugins/  sources/
  sessions/subagent_tasks.jsonl
  logs/trace.jsonl, audit.jsonl
  .workspace
```

### Development conventions (from .cursor/rules.md)

1. **Coding order**: Define interface/base class first → then implementation → then wire into entry points
2. **Directory discipline**: core logic in `core/`, memory in `memory/`, tools in `tools/`, config in `config/`, infra in `infra/`
3. All classes and key functions must have Chinese docstrings
4. Must add logging for traceability
5. Must handle exceptions — no unprotected crashes in main flows
6. All changes must include tests

### Test naming convention

Stage-based tests (`test_stage12_*.py`, `test_stage19_*.py`) cover end-to-end capabilities across subsystems. Feature-specific tests (`test_pipeline.py`, `test_retriever.py`) cover individual modules.

### Recent focus (stage19)

QQ channel integration (NapCat), real-channel production hardening, security/permissions, marketplace indexing, and ops audit/metrics.
