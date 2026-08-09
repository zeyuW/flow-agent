# ServiceApp Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate process entry from application lifecycle by introducing `ServiceApp.init()`, `start()`, `wait()`, and `stop()`.

**Architecture:** `bootstrap.service_app.ServiceApp` owns runtime construction, service startup, stop signaling, thread joins, and workspace lock ownership. `bootstrap.main.main()` only loads configuration, invokes the lifecycle methods, handles `KeyboardInterrupt`, and guarantees cleanup. `start()` is non-blocking; `wait()` blocks the main thread; `stop()` signals components, joins threads, closes resources, and releases the lock.

**Tech Stack:** Python 3.11+, threading, asyncio, pytest, Black.

## Global Constraints

- `start()` must return after starting background services and must not call `join()` on service threads.
- `wait()` must block until the application stop event is set.
- `stop()` must be idempotent and must not join the current thread.
- Stop order must prevent new inbound work before joining worker threads.
- `bootstrap.service.py` is replaced by `bootstrap.service_app.py` and `bootstrap.main.py`; no compatibility entrypoint is retained.
- Preserve existing service behavior and startup script functionality.

---

### Task 1: Add failing lifecycle tests

**Files:**
- Create: `backend/tests/infrastructure/test_service_app_lifecycle.py`
- Modify: `backend/tests/infrastructure/test_service_entrypoint.py`

**Interfaces:**
- Consumes: the intended `ServiceApp` and `main` APIs.
- Produces: tests that fail until the new lifecycle modules exist.

- [x] **Step 1: Test `wait()` blocking and release**

Create a test that starts `ServiceApp.wait()` on a helper thread, asserts it remains blocked, sets the app stop event through the public stop signal, and asserts the waiter exits.

- [x] **Step 2: Test `main()` lifecycle ordering**

Monkeypatch `bootstrap.main.load_application_config` and `bootstrap.main.ServiceApp` with a recorder fake. Call `main()` and assert the order is `init`, `start`, `wait`, `stop`, including `stop` when `wait` raises `KeyboardInterrupt`.

- [x] **Step 3: Run the new tests and verify RED**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q tests/infrastructure/test_service_app_lifecycle.py tests/infrastructure/test_service_entrypoint.py
```

Expected: FAIL because `bootstrap.service_app` and `bootstrap.main` do not exist yet.

### Task 2: Implement `ServiceApp`

**Files:**
- Create: `backend/src/bootstrap/service_app.py`

**Interfaces:**
- Consumes: `AppConfig`, `create_app_runtime`, configured channel and runtime components.
- Produces: `ServiceApp(config)`, `init()`, `start()`, `wait()`, and idempotent `stop()`.

- [x] **Step 1: Implement initialization without starting service threads**

Move runtime creation, channel construction, Telegram tool registration, and lifecycle state setup into `init()`. Acquire the process lock before creating runtime resources. On initialization failure, release the lock and re-raise.

- [x] **Step 2: Implement non-blocking startup**

Move channel, worker, scheduler, optimizer, proactive, and MessageBus dispatch startup into `start()`. Track every thread and event-loop holder on the instance. Do not join any started thread in `start()`.

- [x] **Step 3: Implement `wait()`**

Block on a `threading.Event` owned by `ServiceApp`. `stop()` sets the event so tests and future programmatic shutdowns can release the main thread without relying on `KeyboardInterrupt`.

- [x] **Step 4: Implement ordered, idempotent `stop()`**

Stop inbound channels first, signal proactive/memory/chat/background/subagent/plugin/MCP components, stop MessageBus dispatch through its event loop, join tracked threads with bounded timeouts, close remaining resources, and release the workspace lock exactly once.

- [x] **Step 5: Run lifecycle tests and verify GREEN**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q tests/infrastructure/test_service_app_lifecycle.py tests/infrastructure/test_service_entrypoint.py
```

Expected: PASS.

### Task 3: Add the process entrypoint and remove the old module

**Files:**
- Create: `backend/src/bootstrap/main.py`
- Delete: `backend/src/bootstrap/service.py`
- Modify: `scripts/start.sh`
- Modify: `backend/tests/infrastructure/test_service_entrypoint.py`

**Interfaces:**
- Consumes: `ServiceApp` and `load_application_config`.
- Produces: `bootstrap.main.main()` as the only process entrypoint.

- [x] **Step 1: Implement `main()`**

Load configuration, instantiate `ServiceApp`, call `init()`, `start()`, and `wait()` in order, catch `KeyboardInterrupt`, and always call `stop()` in `finally`.

- [x] **Step 2: Point the startup script to `bootstrap.main`**

Change only the module argument in `scripts/start.sh` from `bootstrap.service` to `bootstrap.main`.

- [x] **Step 3: Remove the old entrypoint and update AST coverage**

Delete `service.py`; update the entrypoint test to assert `main.py` contains the `__main__` guard and calls `main()`.

- [x] **Step 4: Verify direct script syntax and entrypoint imports**

```bash
bash -n scripts/start.sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q tests/infrastructure/test_service_app_lifecycle.py tests/infrastructure/test_service_entrypoint.py
```

Expected: PASS.

### Task 4: Run complete verification

**Files:**
- Modify: only files identified by failing verification.

**Interfaces:**
- Consumes: the new ServiceApp lifecycle and `bootstrap.main` entrypoint.
- Produces: verified startup, shutdown, and test compatibility.

- [x] **Step 1: Confirm no old entrypoint references remain**

```bash
rg -n "bootstrap\.service|run_service|run_from_project|_run_service" backend/src backend/tests scripts --glob '*.py' --glob '*.sh'
```

Expected: no output.

- [x] **Step 2: Run the full backend test suite**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q
```

- [x] **Step 3: Run formatting and compilation checks**

```bash
uv run python -m black --check src/bootstrap/service_app.py src/bootstrap/main.py tests/infrastructure/test_service_app_lifecycle.py tests/infrastructure/test_service_entrypoint.py
python -m compileall -q src tests
```

- [x] **Step 4: Verify the startup script points to the new entrypoint**

```bash
rg -n "bootstrap\.main" scripts/start.sh
```
