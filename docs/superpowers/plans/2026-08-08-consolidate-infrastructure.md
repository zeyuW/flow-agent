# Consolidate Infrastructure Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate over-fragmented shared infrastructure modules while keeping business-specific adapters under their application feature.

**Architecture:** Group small top-level infrastructure files by cohesive technical capability: configuration, persistence, resilience, security, telemetry, workers, runtime lifecycle, and workspace management. Keep the bus package split by transport/event/queue responsibilities because those files are already substantive. Remove the unused duplicate `InfraContainer`; `bootstrap` remains the only composition root.

**Tech Stack:** Python 3.11+, Pydantic, SQLite, threading, pytest, Black.

## Global Constraints

- `infra` contains only cross-business technical capabilities.
- `application/<feature>/infra` remains available for feature-owned persistence and adapters.
- Every consolidated module gets a module-level docstring describing its package role.
- No compatibility modules or old import paths are retained.
- Runtime behavior and public class/function behavior remain unchanged.
- Preserve unrelated existing worktree changes.

---

### Task 1: Establish the target layout contract

- [x] Add `tests/architecture/test_infra_layout.py`.
- [x] Run the focused layout tests and confirm RED before moving files.

### Task 2: Consolidate configuration, persistence, resilience, security, and workers

- [x] Create `infra/config.py`, `infra/persistence.py`, `infra/resilience.py`, `infra/security.py`, and `infra/worker.py` with package-level documentation.
- [x] Update all source and test imports.
- [x] Remove the old directories and their package exports.
- [x] Run focused configuration, persistence, resilience, security, and worker tests.

### Task 3: Consolidate telemetry and lifecycle/workspace infrastructure

- [x] Create `infra/telemetry.py`, `infra/runtime.py`, and `infra/workspace.py` with package-level documentation.
- [x] Update bootstrap, interfaces, tests, and internal imports.
- [x] Remove `infra/lifecycle` and old telemetry package files.
- [x] Run focused telemetry, workspace, lifecycle, and bootstrap tests.

### Task 4: Consolidate bus data types and remove the duplicate infra container

- [x] Create `infra/bus/types.py` by combining contracts and message models.
- [x] Update bus, application, interface, bootstrap, and test imports.
- [x] Remove `infra/bus/contracts.py`, `infra/bus/models.py`, and `infra/container.py`.
- [x] Remove tests that only validate the deleted duplicate container and update public export tests.

### Task 5: Verify the final package layout and behavior

- [x] Confirm no old infrastructure import paths remain.
- [x] Run the complete backend test suite.
- [x] Run Black, compileall, and the layout/import architecture tests.
