# DDD Refactor Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `backend/src` 模块化 DDD 工程边界，并以无循环、显式注入的单向配置系统替换现有全局配置实现，同时保持全部现有产品行为。

**Architecture:** 先把现有 Python 工程机械移动到 `backend/`，把旧业务包保留为 `backend/src/flow_agent` 迁移期实现，再建立 `modules`、`interfaces`、`infra` 和 `bootstrap` 包根。新配置只存在于 `infra.config`，由 Bootstrap 加载并向旧运行时显式传递；本阶段不迁移具体业务模块。

**Tech Stack:** Python 3.10+、Pydantic 2.11+、Setuptools、Pytest 9+、标准库 `tomllib`、Python 3.10 条件依赖 `tomli`。

**状态：** 已确认

## Global Constraints

- 必须保留当前全部产品能力和 238 个基线测试表达的行为。
- 不保留旧配置 API、旧配置字段、旧 Python 导入路径或旧内部接口兼容层。
- 所有新增或修改的解释性注释、文档字符串和待办标记必须使用中文。
- Domain 不得导入 Application、Infra、Interfaces 或 Bootstrap；Application 不得导入具体 Infra、Interfaces 或 Bootstrap。
- 不得修改任务范围外的工程，不得在源码、测试、文档、配置或日志中泄露外部来源名称、路径或品牌。
- 不引入依赖注入框架、全局 Settings Proxy、全局服务定位器或模块级可变依赖容器。
- 每个任务遵循测试先行，并在独立验证通过后提交。
- 当前全项目 Pyright 基线为 184 个错误；新增配置与架构模块必须零错误，且全项目错误数不得增加。

---

## File Responsibility Map

| 文件或目录 | 单一职责 |
| --- | --- |
| `backend/src/modules/__init__.py` | 标识业务模块包根；第一阶段不承载业务实现 |
| `backend/src/interfaces/__init__.py` | 标识外部协议适配器包根 |
| `backend/src/infra/config/schema.py` | 定义不可变、严格校验的运行配置模型 |
| `backend/src/infra/config/loader.py` | 将一个 TOML 文件纯函数式加载为 `AppConfig` |
| `backend/src/infra/config/watcher.py` | 执行配置候选资源的准备—提交两阶段更新 |
| `backend/src/bootstrap/config.py` | 解析配置路径并调用唯一 Loader |
| `backend/src/bootstrap/cli.py` | CLI 入口与运行时启动边界 |
| `backend/src/flow_agent/**` | 迁移期旧业务实现；除配置消费者外不改业务边界 |
| `backend/tests/architecture/import_graph.py` | 构建静态内部导入图并查找循环 |
| `backend/tests/architecture/test_source_layout.py` | 验证 Python 工程边界和包来源 |
| `backend/tests/architecture/test_project_dependencies.py` | 验证模块内分层、跨模块和组合根依赖规则 |
| `backend/tests/infra/config/test_schema.py` | 验证配置不可变性和跨字段约束 |
| `backend/tests/infra/config/test_loader.py` | 验证单一 TOML 配置源 |
| `backend/tests/infra/config/test_watcher.py` | 验证两阶段提交、失败清理和修订去重 |
| `backend/config.example.toml` | 提供不含真实凭据的部署配置示例 |

---

### Task 1: Establish the `backend/src` Project Boundary

**Files:**
- Create: `backend/README.md`
- Create: `backend/tests/architecture/test_source_layout.py`
- Move: `flow_agent/` → `backend/src/flow_agent/`
- Move: `tests/` → `backend/tests/`
- Move: `pyproject.toml` → `backend/pyproject.toml`
- Move: `uv.lock` → `backend/uv.lock`
- Create: `backend/src/modules/__init__.py`
- Create: `backend/src/interfaces/__init__.py`
- Create: `backend/src/infra/__init__.py`
- Create: `backend/src/bootstrap/__init__.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Consumes: 当前 `flow_agent` 包、测试套件和 `flow_agent.main:main` CLI 入口。
- Produces: 可从 `backend/src` 解析的 `flow_agent`、`modules`、`interfaces`、`infra`、`bootstrap` 五个迁移期包。

- [ ] **Step 1: Write the failing source-layout test**

```python
from importlib.util import find_spec
from pathlib import Path


BACKEND_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = BACKEND_ROOT / "src"
REPOSITORY_ROOT = BACKEND_ROOT.parent


def test_python_packages_resolve_from_backend_src():
    for package_name in ("flow_agent", "modules", "interfaces", "infra", "bootstrap"):
        spec = find_spec(package_name)
        assert spec is not None
        locations = list(spec.submodule_search_locations or ())
        assert locations
        assert Path(locations[0]).resolve().is_relative_to(SOURCE_ROOT.resolve())


def test_legacy_python_package_is_not_at_repository_root():
    assert not (REPOSITORY_ROOT / "flow_agent").exists()
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/architecture/test_source_layout.py -q`

Expected: FAIL because the `backend/` Python project boundary does not exist.

- [ ] **Step 3: Move the existing Python project mechanically**

```bash
mkdir -p backend/src
git mv flow_agent backend/src/flow_agent
git mv tests backend/tests
git mv pyproject.toml backend/pyproject.toml
git mv uv.lock backend/uv.lock
```

Create the four package markers with these exact Chinese package docstrings and no import side effects:

```python
# backend/src/modules/__init__.py
"""业务模块包根：业务代码按限界上下文聚合。"""

# backend/src/interfaces/__init__.py
"""外部接口包根：负责协议接入与结果映射。"""

# backend/src/infra/__init__.py
"""共享基础设施包根：提供无业务语义的技术能力。"""

# backend/src/bootstrap/__init__.py
"""组合根包：负责配置加载、依赖装配与进程生命周期。"""
```

- [ ] **Step 4: Configure Setuptools and Pytest**

Update `backend/pyproject.toml`:

```toml
[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
include = ["flow_agent*", "modules*", "interfaces*", "infra*", "bootstrap*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[project.scripts]
flow-agent = "flow_agent.main:main"
```

Create `backend/README.md` with the exact development commands:

````markdown
# 后端开发

从仓库根目录执行：

```bash
.venv/bin/python -m pip install -e backend
.venv/bin/python -m pytest backend/tests -q
```
````

- [ ] **Step 5: Verify imports and behavior**

Run:

```bash
.venv/bin/python -m pip install -e backend
.venv/bin/python -m pytest backend/tests/architecture/test_source_layout.py -q
.venv/bin/python -c "import bootstrap, flow_agent, infra, interfaces, modules"
.venv/bin/python -m pytest backend/tests -q
```

Expected: layout tests PASS, imports exit 0, full suite reports 238 passed.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "refactor: establish backend source boundary"
```

---

### Task 2: Add the Static Import-Graph Analyzer

**Files:**
- Create: `backend/tests/architecture/__init__.py`
- Create: `backend/tests/architecture/import_graph.py`
- Create: `backend/tests/architecture/test_import_graph.py`

**Interfaces:**
- Consumes: Python 源码根目录和参与分析的顶层包名集合。
- Produces: `build_import_graph(source_root, package_roots) -> dict[str, set[str]]` 和 `find_import_cycles(graph) -> list[tuple[str, ...]]`。

- [ ] **Step 1: Write failing analyzer tests**

```python
from tests.architecture.import_graph import build_import_graph, find_import_cycles


def test_import_graph_finds_cycle(tmp_path):
    source = tmp_path / "src"
    package = source / "sample"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "a.py").write_text("from sample.b import value\n", encoding="utf-8")
    (package / "b.py").write_text("from sample.a import value\n", encoding="utf-8")

    graph = build_import_graph(source, {"sample"})

    assert find_import_cycles(graph) == [("sample.a", "sample.b")]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/architecture/test_import_graph.py -q`

Expected: FAIL because `tests.architecture.import_graph` does not exist.

- [ ] **Step 3: Implement the analyzer**

```python
from __future__ import annotations

import ast
from pathlib import Path


ImportGraph = dict[str, set[str]]


def build_import_graph(source_root: Path, package_roots: set[str]) -> ImportGraph:
    modules: dict[str, Path] = {}
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root)
        if relative.parts[0] not in package_roots:
            continue
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = path

    graph: ImportGraph = {module: set() for module in modules}
    for source, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_from_import(source, path, node)
                if base:
                    names.append(base)
                    names.extend(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            for imported in names:
                target = _resolve_module(imported, modules)
                if target is not None and target != source:
                    graph[source].add(target)
    return graph
```

Add `_resolve_from_import` for relative imports and `_resolve_module` for longest existing module-prefix matching. Implement `find_import_cycles` with Tarjan strongly connected components, returning only components larger than one and sorting the result.

- [ ] **Step 4: Run analyzer tests**

Run: `.venv/bin/python -m pytest backend/tests/architecture/test_import_graph.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/architecture
git commit -m "test: add static import graph analyzer"
```

---

### Task 3: Define the Immutable Configuration Schema

**Files:**
- Create: `backend/src/infra/config/__init__.py`
- Create: `backend/src/infra/config/schema.py`
- Create: `backend/tests/infra/__init__.py`
- Create: `backend/tests/infra/config/__init__.py`
- Create: `backend/tests/infra/config/test_schema.py`

**Interfaces:**
- Consumes: 直接对应新 `config.toml` 的嵌套映射。
- Produces: 不可变且拒绝未知字段的 `AppConfig` 和各配置分区类型。

- [ ] **Step 1: Write failing schema tests**

```python
import pytest
from pydantic import ValidationError

from infra.config.schema import AppConfig


def minimal_config() -> dict[str, object]:
    return {"llm": {"main": {"model": "model-main", "api_key": "secret"}}}


def test_config_is_frozen_and_rejects_unknown_fields():
    config = AppConfig.model_validate(minimal_config())
    with pytest.raises(ValidationError):
        config.jobs.max_workers = 8
    raw = minimal_config()
    raw["unknown"] = True
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_enabled_telegram_requires_credentials():
    raw = minimal_config()
    raw["channels"] = {"telegram_enabled": True}
    with pytest.raises(ValidationError, match="Telegram"):
        AppConfig.model_validate(raw)
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/infra/config/test_schema.py -q`

Expected: FAIL because `infra.config.schema` does not exist.

- [ ] **Step 3: Implement the strict base and main types**

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenConfig(BaseModel):
    """所有运行配置的不可变严格基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelEndpointConfig(FrozenConfig):
    model: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    base_url: str | None = None


class MainModelConfig(ModelEndpointConfig):
    system_prompt: str = "You are a helpful AI assistant."
    enable_thinking: bool = True


class LLMConfig(FrozenConfig):
    main: MainModelConfig
    fast: ModelEndpointConfig | None = None
    vision: ModelEndpointConfig | None = None
    fallback_enabled: bool = True
```

Implement the remaining sections with these stable defaults:

| 类型 | 字段与默认值 |
| --- | --- |
| `EmbeddingConfig` | `provider="qwen"`, `model="text-embedding-v3"`, `api_key=None`, `base_url=None` |
| `StorageConfig` | `memory_db_path=".flow/data/memory.db"`, `outbox_recovery_window_seconds=0.0`, `outbox_recovery_limit=100` |
| `SessionConfig` | `default_id="default"`, `max_history_messages=500`, `cache_size=64`, `undo_enabled=True` |
| `ToolingConfig` | `enabled=True`, `max_steps=5`, `selection_limit=8` |
| `MemoryConfig` | `enabled=True`, `max_messages=100`, `deduplicate=True`, `recent_turn_limit=8` |
| `ProactiveConfig` | `enabled=False`, `target_user_id=None`, `max_per_day=10`, `min_interval_seconds=60.0`, `max_interval_seconds=600.0`, `cooldown_seconds=60.0` |
| `ChannelsConfig` | `telegram_enabled=False`, `telegram_bot_token=None`, `telegram_allowed_users=()` |
| `JobsConfig` | `max_queue_size=64`, `max_workers=4`, `shutdown_timeout_seconds=30.0` |
| `DelegationConfig` | `enabled=True`, `max_concurrency=2`, `tasks_file=".flow/sessions/subagent_tasks.jsonl"` |
| `ObservabilityConfig` | `enabled=True`, `trace_path=".flow/logs/trace.jsonl"` |

Use `Field` to enforce positive queue, worker, timeout and limit values. `ChannelsConfig` validates Telegram credentials when enabled. `ProactiveConfig` validates a non-empty target when enabled and `min_interval_seconds <= max_interval_seconds`.

- [ ] **Step 4: Implement the top-level schema**

```python
class AppConfig(FrozenConfig):
    llm: LLMConfig
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    tooling: ToolingConfig = Field(default_factory=ToolingConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    delegation: DelegationConfig = Field(default_factory=DelegationConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
```

Export configuration types from `infra.config.__init__` without importing Loader or Watcher.

- [ ] **Step 5: Verify schema tests and types**

Run:

```bash
.venv/bin/python -m pytest backend/tests/infra/config/test_schema.py -q
.venv/bin/python -m pyright --pythonpath .venv/bin/python backend/src/infra/config/schema.py backend/tests/infra/config/test_schema.py
```

Expected: tests PASS and scoped Pyright reports 0 errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/infra/config backend/tests/infra
git commit -m "feat: add immutable application configuration"
```

---

### Task 4: Load One TOML File Directly Into the Schema

**Files:**
- Create: `backend/src/infra/config/loader.py`
- Create: `backend/tests/infra/config/test_loader.py`
- Create: `backend/config.example.toml`
- Modify: `.gitignore`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Consumes: `pathlib.Path` pointing to exactly one TOML file。
- Produces: `load_config(path: Path) -> AppConfig`；不缓存、不搜索备用路径、不读取环境变量。

- [ ] **Step 1: Write failing loader tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from infra.config.loader import load_config


def test_load_config_maps_toml_directly(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[llm.main]\nmodel="main-model"\napi_key="secret"\n[jobs]\nmax_workers=3\n',
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.llm.main.model == "main-model"
    assert config.jobs.max_workers == 3


def test_load_config_does_not_read_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FLOW_AGENT_LLM_MAIN_API_KEY", "environment-secret")
    path = tmp_path / "config.toml"
    path.write_text('[llm.main]\nmodel="main-model"\n', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/infra/config/test_loader.py -q`

Expected: FAIL because `infra.config.loader` does not exist.

- [ ] **Step 3: Implement the pure loader**

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from infra.config.schema import AppConfig


def load_config(path: Path) -> AppConfig:
    """读取唯一 TOML 配置源并返回完整不可变快照。"""

    with path.open("rb") as config_file:
        raw: dict[str, Any] = tomllib.load(config_file)
    return AppConfig.model_validate(raw)
```

Do not add cache, YAML support, environment fallback, project-root discovery or LLM-specific Builders.

- [ ] **Step 4: Add dependency, ignore rule and safe example**

Add to `backend/pyproject.toml` dependencies:

```toml
"tomli>=2.0; python_version < '3.11'",
```

Add exact ignore rules:

```gitignore
backend/config.toml
!backend/config.example.toml
```

Create `backend/config.example.toml` with `[llm.main]`、`[channels]`、`[proactive]`、`[jobs]` and `[delegation]` sections. Required credentials use `replace-me`，中文注释解释字段，不得包含真实凭据。

- [ ] **Step 5: Verify loader and example**

Run:

```bash
.venv/bin/python -m pytest backend/tests/infra/config/test_loader.py -q
.venv/bin/python -c "from pathlib import Path; from infra.config.loader import load_config; load_config(Path('backend/config.example.toml'))"
```

Expected: tests PASS and example loading exits 0.

- [ ] **Step 6: Commit**

```bash
git add .gitignore backend/pyproject.toml backend/config.example.toml backend/src/infra/config/loader.py backend/tests/infra/config/test_loader.py
git commit -m "feat: load config from one TOML source"
```

---

### Task 5: Implement Two-Phase Configuration Reloading

**Files:**
- Create: `backend/src/infra/config/watcher.py`
- Create: `backend/tests/infra/config/test_watcher.py`

**Interfaces:**
- Consumes: 当前 `AppConfig`、`load_config` 和多个 `ConfigApplier`。
- Produces: `PreparedConfigChange(commit, discard)`、`ConfigApplier.prepare(current, candidate)`、`ConfigWatcher.reload_once() -> bool`。

- [ ] **Step 1: Write failing two-phase tests**

```python
from pathlib import Path

from infra.config.schema import AppConfig
from infra.config.watcher import ConfigWatcher, PreparedConfigChange


def config(model: str) -> AppConfig:
    return AppConfig.model_validate(
        {"llm": {"main": {"model": model, "api_key": "secret"}}}
    )


def test_prepare_failure_discards_candidates_and_keeps_current(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("revision-one", encoding="utf-8")
    actions: list[str] = []

    class PreparedApplier:
        def prepare(self, current: AppConfig, candidate: AppConfig):
            return PreparedConfigChange(
                commit=lambda: actions.append("commit"),
                discard=lambda: actions.append("discard"),
            )

    class FailingApplier:
        def prepare(self, current: AppConfig, candidate: AppConfig):
            raise ValueError("invalid runtime patch")

    old = config("old")
    watcher = ConfigWatcher(
        path,
        current=old,
        appliers=(PreparedApplier(), FailingApplier()),
        loader=lambda _: config("new"),
    )
    path.write_text("revision-two", encoding="utf-8")

    assert watcher.reload_once() is False
    assert actions == ["discard"]
    assert watcher.current is old
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/infra/config/test_watcher.py -q`

Expected: FAIL because `infra.config.watcher` does not exist.

- [ ] **Step 3: Implement exact data contracts**

```python
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from infra.config.loader import load_config
from infra.config.schema import AppConfig


@dataclass(frozen=True, slots=True)
class PreparedConfigChange:
    commit: Callable[[], None]
    discard: Callable[[], None]


class ConfigApplier(Protocol):
    def prepare(
        self,
        current: AppConfig,
        candidate: AppConfig,
    ) -> PreparedConfigChange: ...
```

`ConfigWatcher.reload_once()` must：读取文件修订、忽略已处理修订、加载候选配置、顺序 Prepare、失败时逆序 Discard、全部成功后顺序 Commit、最后更新 `current`。Commit 回调只能执行不会失败的赋值或原子交换。

- [ ] **Step 4: Verify watcher tests and types**

Run:

```bash
.venv/bin/python -m pytest backend/tests/infra/config/test_watcher.py -q
.venv/bin/python -m pyright --pythonpath .venv/bin/python backend/src/infra/config backend/tests/infra/config
```

Expected: tests PASS and scoped Pyright reports 0 errors.

- [ ] **Step 5: Commit**

```bash
git add backend/src/infra/config/watcher.py backend/tests/infra/config/test_watcher.py
git commit -m "feat: add transactional config reload"
```

---

### Task 6: Inject Configuration and Delete the Legacy Cycle

**Files:**
- Create: `backend/src/bootstrap/config.py`
- Create: `backend/src/bootstrap/cli.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/flow_agent/main.py`
- Modify: `backend/src/flow_agent/app/bootstrap.py`
- Modify: `backend/src/flow_agent/core/agent.py`
- Modify: `backend/src/flow_agent/llm/client.py`
- Replace: `backend/tests/test_config.py`
- Delete: `backend/src/flow_agent/config/`
- Delete: `backend/src/flow_agent/llm/config.py`

**Interfaces:**
- Consumes: `load_config(path) -> AppConfig` 和现有运行时工厂。
- Produces: `bootstrap.config.load_application_config(backend_root: Path) -> AppConfig`、`bootstrap.cli.main(argv: Sequence[str] | None = None) -> int`、显式接收配置的运行时构造函数。

- [ ] **Step 1: Write failing bootstrap tests**

```python
from pathlib import Path

from bootstrap.config import load_application_config


def test_bootstrap_loads_only_backend_config(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        '[llm.main]\nmodel="main-model"\napi_key="secret"\n',
        encoding="utf-8",
    )

    config = load_application_config(tmp_path)

    assert config.llm.main.model == "main-model"
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_config.py backend/tests/test_agent.py -q`

Expected: FAIL because Bootstrap and explicit constructor signatures do not exist.

- [ ] **Step 3: Implement the Bootstrap boundary**

```python
from pathlib import Path

from infra.config.loader import load_config
from infra.config.schema import AppConfig


def load_application_config(backend_root: Path) -> AppConfig:
    """从后端根目录加载唯一运行配置。"""

    return load_config(backend_root / "config.toml")
```

Set the CLI entry to:

```toml
[project.scripts]
flow-agent = "bootstrap.cli:main"
```

`bootstrap.cli.main` parses CLI arguments, loads `AppConfig` once and calls `flow_agent.main.run_service(config)`。Bootstrap must not create network clients at import time.

- [ ] **Step 4: Make runtime dependencies explicit**

Apply these exact constructor transformations:

```python
def run_service(config: AppConfig) -> None:
    lock = WorkspaceProcessLock(WORKSPACE_LAYOUT.flow_dir / "runtime.lock")
    try:
        lock.acquire()
    except WorkspaceAlreadyRunningError as exc:
        print(f"启动失败：{exc}")
        return
    try:
        _run_service(config)
    finally:
        lock.release()


def create_app_runtime(config: AppConfig):
    cfg = config
    # 后续组装逻辑继续使用局部 cfg，不再读取模块级配置。


class Agent:
    def __init__(
        self,
        system_prompt: str,
        llm_client: LLMClient,
        context: ConversationContext,
        session_id: str = "default",
        llm_router: LLMRouter | None = None,
        prompt_assembler: PromptAssembler | None = None,
        persona_resolver: PersonaResolver | None = None,
        vision_client: LLMClient | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.llm_client = llm_client
        self.context = context
        self.session_id = session_id
        self.llm_router = llm_router
        self.prompt_assembler = prompt_assembler
        self.persona_resolver = persona_resolver
        self.vision_client = vision_client


class OpenAILLMClient:
    def __init__(self, config: ModelEndpointConfig) -> None:
        self.model = config.model
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.async_client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
```

Replace `self.settings.system_prompt` with `self.system_prompt` in Agent. Replace every `settings.get()` and module-level configuration read in the construction path with values passed from `create_app_runtime(config)`。No downstream object may retain the complete `AppConfig` unless it applies configuration changes.

- [ ] **Step 5: Remove old configuration modules only after consumers are gone**

Run:

```bash
rg -n 'flow_agent\.config|flow_agent\.llm\.config|settings\.get' backend/src backend/tests
```

Expected before deletion: no active consumers outside the files scheduled for deletion. Then delete the legacy configuration directory and LLM Builder file with `git rm`.

- [ ] **Step 6: Verify the migrated runtime**

Run:

```bash
.venv/bin/python -m pytest backend/tests/test_config.py backend/tests/test_agent.py backend/tests/test_message_bus_architecture.py backend/tests/test_passive_turn_concurrency.py backend/tests/test_telegram_multimodal.py -q
.venv/bin/python -m pytest backend/tests -q
```

Expected: focused tests PASS and full suite reports 238 passed.

- [ ] **Step 7: Commit**

```bash
git add backend
git commit -m "refactor: inject runtime configuration explicitly"
```

---

### Task 7: Enforce Modular Dependency Rules and Complete Verification

**Files:**
- Create: `backend/tests/architecture/test_project_dependencies.py`
- Create: `scripts/verify-backend.sh`
- Modify: `backend/tests/test_ci_verification.py`
- Modify: `docs/specs/2026-08-01-ddd-refactor/tasks.md`

**Interfaces:**
- Consumes: Task 2 的静态导入图和最终 `backend/src`。
- Produces: 默认 Pytest 执行的无循环、分层、跨模块和组合根门禁。

- [ ] **Step 1: Write failing project architecture tests**

```python
from pathlib import Path

from tests.architecture.import_graph import build_import_graph, find_import_cycles


BACKEND_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = BACKEND_ROOT / "src"
PACKAGE_ROOTS = {"flow_agent", "modules", "interfaces", "infra", "bootstrap"}


def graph():
    return build_import_graph(SOURCE_ROOT, PACKAGE_ROOTS)


def test_project_import_graph_has_no_cycles():
    assert find_import_cycles(graph()) == []


def test_only_bootstrap_may_compose_concrete_layers():
    violations: list[tuple[str, str]] = []
    for source, targets in graph().items():
        if source.startswith("bootstrap"):
            continue
        for target in targets:
            if source.startswith("modules.") and target.startswith("interfaces."):
                violations.append((source, target))
            if source.startswith("interfaces.") and ".infra." in target:
                violations.append((source, target))
    assert sorted(violations) == []
```

Add this path-aware assertion helper and enforce the exact rules below:

```python
def layer_of(module: str) -> tuple[str | None, str | None]:
    parts = module.split(".")
    if len(parts) < 3 or parts[0] != "modules":
        return None, None
    module_name = parts[1]
    layer = parts[2] if parts[2] in {"domain", "application", "infra"} else None
    return module_name, layer


def test_module_layer_dependencies_are_one_way():
    violations: list[tuple[str, str]] = []
    for source, targets in graph().items():
        source_module, source_layer = layer_of(source)
        for target in targets:
            target_module, target_layer = layer_of(target)
            if source_layer == "domain" and target_layer in {"application", "infra"}:
                violations.append((source, target))
            if source_layer == "application" and target_layer == "infra":
                violations.append((source, target))
            if (
                source_module is not None
                and target_module is not None
                and source_module != target_module
                and target_layer in {"domain", "infra"}
            ):
                violations.append((source, target))
            if source.startswith("modules.") and target.startswith(
                ("interfaces.", "bootstrap.")
            ):
                violations.append((source, target))
    assert sorted(set(violations)) == []
```

Rules represented by the test:

```text
modules.<name>.domain       !-> application | infra | interfaces | bootstrap
modules.<name>.application  !-> infra | interfaces | bootstrap
modules.<name>              !-> modules.<other>.domain | modules.<other>.infra
flow_agent                  !-> interfaces | bootstrap
```

- [ ] **Step 2: Run tests and verify violations are reported**

Run: `.venv/bin/python -m pytest backend/tests/architecture/test_project_dependencies.py -q`

Expected: FAIL until the source layout and configuration cycle migrations from previous tasks are complete.

- [ ] **Step 3: Add the backend verification script**

```bash
#!/usr/bin/env bash
set -euo pipefail

.venv/bin/python -m compileall -q backend/src
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m pyright --pythonpath .venv/bin/python backend/src/infra/config backend/tests/architecture backend/tests/infra/config
.venv/bin/python -m black --check --target-version py310 --fast backend/src backend/tests
git diff --check
```

Make `backend/tests/test_ci_verification.py` assert that the script includes compileall、default Pytest、scoped Pyright、Black and `git diff --check`。

- [ ] **Step 4: Run complete verification**

Run:

```bash
bash scripts/verify-backend.sh
git diff --check
git status --short
```

然后从工作区根目录执行工作区约定中的来源隔离检查。Expected: verification script exits 0; source-isolation scan has no matches; diff check exits 0; status contains only planned files.

- [ ] **Step 5: Mark completed checkboxes and commit**

Change only completed task checkboxes from `[ ]` to `[x]`, then run:

```bash
git add backend scripts docs/specs/2026-08-01-ddd-refactor
git commit -m "test: enforce modular architecture boundaries"
```

---

## Phase Completion Gate

Phase 1 is complete only when all conditions hold:

- `backend/src` is the only Python package root.
- All 238 baseline tests pass from `backend/tests`.
- The static import graph has no cycles.
- The existing configuration cycle is deleted rather than hidden behind a compatibility wrapper.
- New config and architecture files report zero scoped Pyright errors.
- No credentials, external source names or unrelated changes appear in the diff.
- `git diff --check` exits 0.

After this gate, the next plan starts with Delivery and Conversation migration; it must not expand Phase 1 by moving unrelated business code.
