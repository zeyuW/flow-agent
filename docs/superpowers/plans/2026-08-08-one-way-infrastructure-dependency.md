# One-Way Infrastructure Dependency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove top-level `infra → application` imports while preserving the project’s intentional `application → infra` and feature-local `app → infra` dependencies.

**Architecture:** Move the transport contracts currently owned by `application.ports` into `infra.bus.contracts`, because this project treats infrastructure as the lower layer that application code consumes. Update all production code and tests to import those contracts from `infra.bus.contracts`. Add an architecture test that forbids any `application`, `interfaces`, or `bootstrap` import from `src/infra`.

**Tech Stack:** Python 3.11+, pytest, dataclasses, typing.Protocol, Black.

## Global Constraints

- `src/infra` must not import `application`, `interfaces`, or `bootstrap`.
- `application` may import top-level `infra` and its own feature-local `application/<feature>/infra` modules.
- Do not add a compatibility re-export under `application.ports`.
- Do not change runtime behavior of MessageBus, ChatWorker, or outbound delivery.
- Preserve all unrelated worktree changes.

---

### Task 1: Establish the dependency-direction test

**Files:**
- Modify: `backend/tests/architecture/test_project_dependencies.py`
- Modify: `backend/tests/architecture/test_application_ports.py`

**Interfaces:**
- Consumes: the existing source import graph and `infra.bus.contracts` names.
- Produces: a failing architecture contract that catches reverse imports and checks the new contract location.

- [x] **Step 1: Update the architecture assertions first**

Change the message contract imports and path assertions from `application.ports` to `infra.bus.contracts`. Remove the exemption for `application.ports` from the shared-infrastructure dependency test. Add an assertion that no source file under `src/infra` imports `application`, `interfaces`, or `bootstrap`.

- [x] **Step 2: Run the focused architecture tests and verify failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q tests/architecture/test_project_dependencies.py tests/architecture/test_application_ports.py
```

Expected: FAIL because `infra.bus.message` still imports `application.ports`, and the new contract module does not exist yet.

### Task 2: Move transport contracts into infrastructure

**Files:**
- Create: `backend/src/infra/bus/contracts.py`
- Modify: `backend/src/infra/bus/message.py:20-24`
- Delete: `backend/src/application/ports/__init__.py`
- Delete: `backend/src/application/ports/message_consumer.py`
- Delete: `backend/src/application/ports/message_sender.py`

**Interfaces:**
- Consumes: existing `MessageSender`, `MessageConsumer`, `SendMessage`, `SendResult`, and `ReceivedMessage` definitions.
- Produces: `infra.bus.contracts.MessageSender`, `infra.bus.contracts.MessageConsumer`, `infra.bus.contracts.SendMessage`, `infra.bus.contracts.SendResult`, and `infra.bus.contracts.ReceivedMessage`.

- [x] **Step 1: Create `infra.bus.contracts` with the existing public contract definitions**

Move the dataclasses and protocols without changing field names, defaults, or method signatures.

- [x] **Step 2: Update `infra.bus.message` to import sibling contracts**

Replace its imports from `application.ports.*` with imports from `.contracts`.

- [x] **Step 3: Delete the old application-owned ports**

Remove the three files under `src/application/ports`; no compatibility shim is allowed by the requested architecture.

- [x] **Step 4: Run the focused architecture tests**

Run the command from Task 1. Expected: the infrastructure dependency and contract-location tests pass; application imports will still fail until Task 3 updates them.

### Task 3: Migrate application, bootstrap, interfaces, and tests

**Files:**
- Modify: `backend/src/application/conversation/app/chat_worker.py`
- Modify: `backend/src/application/conversation/app/pipeline.py`
- Modify: `backend/src/application/proactive/app/deliver.py`
- Modify: `backend/src/application/proactive/app/pipeline.py`
- Modify: `backend/src/application/proactive/app/runtime.py`
- Modify: `backend/src/application/scheduling/app/runtime.py`
- Modify: `backend/src/bootstrap/container.py`
- Modify: `backend/tests/architecture/test_application_ports.py`
- Modify: `backend/tests/integration/test_conversation_delivery_contracts.py`
- Modify: `backend/tests/integration/test_telegram_conversation_flow.py`
- Modify: `backend/tests/infrastructure/test_message_transport.py`
- Modify: `backend/tests/conversation/test_chat_worker.py`

**Interfaces:**
- Consumes: `infra.bus.contracts` from Task 2.
- Produces: all existing callers using the new import path, with unchanged runtime behavior.

- [x] **Step 1: Replace every old production import**

Use `rg` to ensure no production file imports `application.ports`, then update each listed module to import from `infra.bus.contracts`.

- [x] **Step 2: Replace every old test import and path assertion**

Update tests to the new contract namespace; do not preserve old import paths.

- [x] **Step 3: Verify no old namespace remains**

Run:

```bash
rg -n "application\.ports|from application\.ports|import application\.ports" src tests
```

Expected: no output.

- [x] **Step 4: Run focused transport and conversation tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q tests/architecture tests/infrastructure/test_message_transport.py tests/conversation/test_chat_worker.py tests/integration/test_conversation_delivery_contracts.py tests/integration/test_telegram_conversation_flow.py
```

Expected: PASS.

### Task 4: Validate the complete dependency direction

**Files:**
- Modify: none unless validation identifies an import missed by Tasks 2–3.

**Interfaces:**
- Consumes: migrated source tree and tests.
- Produces: verified one-way top-level dependency direction.

- [x] **Step 1: Run all backend tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q
```

- [x] **Step 2: Run formatting and syntax checks**

```bash
uv run python -m black --check src/infra/bus/contracts.py src/infra/bus/message.py src/application/conversation/app/chat_worker.py src/application/conversation/app/pipeline.py src/application/proactive/app/deliver.py src/application/proactive/app/pipeline.py src/application/proactive/app/runtime.py src/application/scheduling/app/runtime.py src/bootstrap/container.py tests/architecture/test_project_dependencies.py tests/architecture/test_application_ports.py
python -m compileall -q src tests
```

- [x] **Step 3: Confirm the final import graph**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q tests/architecture/test_project_dependencies.py
```

Expected: all dependency-direction checks pass, including no imports from `src/infra` into `application`, `interfaces`, or `bootstrap`.
