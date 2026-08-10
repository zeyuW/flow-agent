# Docker Deployment Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Docker deployment script the reliable single entry point for proxy-aware, reproducible Flow Agent startup.

**Architecture:** Keep `FLOW_AGENT_*` as Compose-only internal variables. Refactor the shell entrypoint into sourceable helper functions so pytest can verify proxy normalization and Compose selection without starting Docker. Pass resolved proxy values to both runtime environment and build arguments; install Node.js/npm in the image so configured `npx` MCP servers have their declared runtime.

**Tech Stack:** Bash, Docker Compose v2, Dockerfile, pytest subprocess tests.

## Global Constraints

- Users must only need standard `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`; `FLOW_AGENT_*` remains an internal override layer.
- No proxy variables means empty proxy values and a normal startup path.
- `127.0.0.1` and `localhost` proxy hosts become `host.docker.internal` for container access.
- `host.docker.internal` must be present in `NO_PROXY` without dropping existing entries.
- Legacy Python `docker-compose` must fail with a clear Compose v2 installation message.
- Proxy values must be available during dependency installation but must not be persisted in the final image environment.
- Existing `.flow/` data and user MCP configuration must not be deleted or rewritten by deployment.

---

### Task 1: Add executable tests for deployment proxy behavior

**Files:**
- Create: `backend/tests/infrastructure/test_docker_deploy_script.py`
- Test target: `scripts/docker-deploy.sh`

**Interfaces:**
- Consumes sourceable shell functions `normalize_proxy`, `ensure_no_proxy_host`, and `resolve_proxy_env`.
- Produces regression coverage for standard proxy variables, project overrides, localhost conversion, no-proxy preservation, and empty defaults.

- [ ] **Step 1: Write the failing tests**

Test the script through `bash -c 'source ...'` so tests execute the real shell functions:

```python
def run_bash(function: str, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["bash", "-c", f"source scripts/docker-deploy.sh; {function}"],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def test_normalize_proxy_rewrites_localhost_for_container():
    assert run_bash('normalize_proxy "$1"', "", "http://127.0.0.1:7892") == (
        "http://host.docker.internal:7892"
    )


def test_resolve_proxy_env_reads_standard_variables_and_adds_host_no_proxy():
    env = os.environ.copy()
    env.update({
        "http_proxy": "http://127.0.0.1:7892",
        "https_proxy": "http://127.0.0.1:7892",
        "no_proxy": "localhost,127.0.0.1",
    })
    for key in ("FLOW_AGENT_HTTP_PROXY", "FLOW_AGENT_HTTPS_PROXY", "FLOW_AGENT_NO_PROXY"):
        env.pop(key, None)
    output = run_bash(
        'resolve_proxy_env; printf "%s\\n%s\\n%s" "$FLOW_AGENT_HTTP_PROXY" "$FLOW_AGENT_HTTPS_PROXY" "$FLOW_AGENT_NO_PROXY"',
        env=env,
    )
    assert output.splitlines() == [
        "http://host.docker.internal:7892",
        "http://host.docker.internal:7892",
        "localhost,127.0.0.1,host.docker.internal",
    ]


def test_resolve_proxy_env_defaults_to_empty_without_proxy():
    env = os.environ.copy()
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy",
        "FLOW_AGENT_HTTP_PROXY", "FLOW_AGENT_HTTPS_PROXY", "FLOW_AGENT_NO_PROXY",
    ):
        env.pop(key, None)
    output = run_bash(
        'resolve_proxy_env; printf "%s\\n%s\\n%s" "$FLOW_AGENT_HTTP_PROXY" "$FLOW_AGENT_HTTPS_PROXY" "$FLOW_AGENT_NO_PROXY"',
        env=env,
    )
    assert output.splitlines() == ["", "", "localhost,127.0.0.1,host.docker.internal"]
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run:

```bash
cd backend && uv run pytest tests/infrastructure/test_docker_deploy_script.py -q
```

Expected: FAIL because the script is not yet sourceable and does not expose the helper functions.

### Task 2: Refactor the Docker deployment script and enforce Compose v2

**Files:**
- Modify: `scripts/docker-deploy.sh`
- Test: `backend/tests/infrastructure/test_docker_deploy_script.py`

**Interfaces:**
- `normalize_proxy(value: str) -> stdout`: rewrites local host names.
- `ensure_no_proxy_host(value: str) -> stdout`: preserves comma-separated entries and appends `host.docker.internal` once.
- `resolve_proxy_env()`: sets `FLOW_AGENT_HTTP_PROXY`, `FLOW_AGENT_HTTPS_PROXY`, and `FLOW_AGENT_NO_PROXY` from standard variables.
- `select_compose()`: returns only `docker compose`; emits an actionable error if unavailable.

- [ ] **Step 1: Implement the minimal sourceable shell structure**

Move argument parsing and deployment side effects into `main`, retain the existing config and Docker daemon checks, and guard execution:

```bash
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
```

Use uppercase variables first and lowercase fallbacks. Run `normalize_proxy` for HTTP and HTTPS values, then append `host.docker.internal` to `NO_PROXY`.

- [ ] **Step 2: Make Compose selection reject legacy Compose**

Use:

```bash
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  fatal "未找到 Docker Compose v2，请安装 docker-compose-plugin 后重试；旧版 docker-compose 1.x 不兼容当前 Docker Engine。"
fi
```

- [ ] **Step 3: Force recreation and run focused tests**

Change deployment to `up --build --force-recreate -d`, then run:

```bash
cd backend && uv run pytest tests/infrastructure/test_docker_deploy_script.py -q
bash -n scripts/docker-deploy.sh
```

Expected: all focused tests pass and shell syntax check exits 0.

### Task 3: Pass proxy values into Docker builds without persisting them

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker/Dockerfile`

**Interfaces:**
- Compose build args `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` consume the resolved `FLOW_AGENT_*` values.
- Dockerfile uses `ARG` only in the dependency installation layer and does not declare proxy `ENV` values.

- [ ] **Step 1: Add Compose build arguments**

Add under the service `build` mapping:

```yaml
args:
  HTTP_PROXY: "${FLOW_AGENT_HTTP_PROXY:-}"
  HTTPS_PROXY: "${FLOW_AGENT_HTTPS_PROXY:-}"
  NO_PROXY: "${FLOW_AGENT_NO_PROXY:-localhost,127.0.0.1,host.docker.internal}"
```

- [ ] **Step 2: Use build arguments only for pip installation**

Add `ARG` declarations before the `RUN pip install` layer and invoke pip with both lowercase and uppercase proxy variables scoped to that command:

```dockerfile
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

RUN http_proxy="$HTTP_PROXY" \
    https_proxy="$HTTPS_PROXY" \
    no_proxy="$NO_PROXY" \
    HTTP_PROXY="$HTTP_PROXY" \
    HTTPS_PROXY="$HTTPS_PROXY" \
    NO_PROXY="$NO_PROXY" \
    pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir ./backend
```

- [ ] **Step 3: Validate Compose interpolation and image build definition**

Run:

```bash
docker compose config
docker compose config --images
```

Expected: valid configuration and the expected `flow-agent-flow-agent` image; proxy build args may be empty when no proxy is configured.

### Task 4: Add npx runtime support and document the supported entrypoint

**Files:**
- Modify: `docker/Dockerfile`
- Modify: `README.md`

**Interfaces:**
- The image provides `node`, `npm`, and `npx` for explicitly configured external MCP servers.
- README tells users to use `scripts/docker-deploy.sh` and never requires `FLOW_AGENT_*`.

- [ ] **Step 1: Install Node.js/npm in the image**

Before copying the backend, install Debian’s `nodejs` and `npm` packages with `--no-install-recommends`, then remove APT lists:

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Update Docker documentation**

Document the single startup command, standard optional proxy variables, Compose v2 prerequisite, and that `.flow/mcp.json` may declare `npx`-based MCP servers now supported by the image.

- [ ] **Step 3: Rebuild and verify the runtime image**

Run:

```bash
docker compose build --no-cache flow-agent
docker compose run --rm --no-deps flow-agent sh -lc 'node --version && npm --version && npx --version'
```

Expected: all three commands print versions and exit 0.

### Task 5: Full regression verification

**Files:**
- Test: `backend/tests/infrastructure/test_docker_deploy_script.py`
- Verify: `scripts/docker-deploy.sh`, `docker-compose.yml`, `docker/Dockerfile`

- [ ] **Step 1: Run focused and repository checks**

```bash
cd backend && uv run pytest tests/infrastructure/test_docker_deploy_script.py -q
cd backend && uv run pytest -q
bash -n scripts/docker-deploy.sh
```

- [ ] **Step 2: Run the real deployment with a proxy**

```bash
export http_proxy=http://127.0.0.1:7892
export https_proxy=http://127.0.0.1:7892
export no_proxy=localhost,127.0.0.1,host.docker.internal
./scripts/docker-deploy.sh --no-logs
docker compose exec flow-agent env | grep -i proxy
docker compose logs --tail=100 flow-agent
```

Expected: the script reports `docker compose`, runtime proxy values use `host.docker.internal`, the container is `Up`, and MCP startup no longer fails with `npx` missing.
