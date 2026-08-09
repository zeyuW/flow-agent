# Update Project Readmes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the repository and backend README files so new users can start Flow Agent quickly and developers can understand the actual source layout and dependency direction.

**Architecture:** Keep the root README concise and operational. Put detailed package responsibilities, the current aggregated `infra` modules, startup lifecycle, and one-way dependency rules in `backend/README.md`.

**Tech Stack:** Markdown, Bash, Python `uv`, pytest.

## Global Constraints

- Root README must prioritize overall understanding and quick start.
- Backend README must describe the current filesystem and import architecture, not removed compatibility paths.
- Startup instructions must use `scripts/start.sh` and the current `bootstrap.main` entry point.
- Documentation changes must not alter runtime code.

---

### Task 1: Rewrite the root README

**Files:**
- Modify: `README.md`

- [x] Replace outdated startup instructions with the repository-level workflow: copy `config.example.toml`, edit `[llm.main]`, run `./scripts/start.sh`, and stop with `Ctrl+C`.
- [x] Add a compact architecture summary covering `application`, `interfaces`, `infra`, and `bootstrap`.
- [x] Link to `backend/README.md`, configuration example, and uv documentation.

### Task 2: Rewrite the backend README

**Files:**
- Modify: `backend/README.md`

- [x] Document the current `backend/src` and `backend/tests` layout, including business-owned `application/<feature>/infra` versus shared top-level `infra`.
- [x] Explain the dependency direction with a compact diagram and explicit constraints.
- [x] Describe the aggregated infrastructure modules and the bus subpackage.
- [x] Document `bootstrap.main -> ServiceApp.init/start/wait/stop` and the test command with ROS plugin autoload disabled.
- [x] Remove references to deleted `application/ports`, `infra/lifecycle`, and `bootstrap.service` paths.

### Task 3: Validate documentation accuracy

**Files:**
- Test: `scripts/start.sh`, `backend/src/bootstrap/main.py`, `backend/src/infra/*.py`

- [x] Search both README files for removed paths and stale entry points.
- [x] Confirm every command and referenced path exists.
- [x] Inspect the final diff for unrelated changes.
