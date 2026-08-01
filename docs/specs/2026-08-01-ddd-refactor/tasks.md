# DDD Refactor Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立标准 `src/` 四层包骨架，并以无循环、显式注入的单向配置系统替换现有全局配置实现，同时保持全部现有产品行为。

**Architecture:** 先把现有 `flow_agent` 包机械移动到 `src/flow_agent` 作为迁移期旧实现，再创建 `domain`、`application`、`infra`、`interfaces` 四层包。新配置只存在于 `infra.config`，由 `interfaces` 组合根加载并向旧运行时显式传递；阶段结束时删除旧配置包，但暂不迁移其他业务模块。

**Tech Stack:** Python 3.10+、Pydantic 2.11+、Setuptools、Pytest 9+、标准库 `tomllib`、Python 3.10 条件依赖 `tomli`。

**状态：** 已确认

## Global Constraints

- 必须保留当前全部产品能力和 238 个基线测试表达的行为。
- 不保留旧配置 API、旧配置字段、旧 Python 导入路径或旧内部接口兼容层。
- 所有新增或修改的解释性注释、文档字符串和待办标记必须使用中文。
- `domain` 不得导入其他三层；`application` 不得导入 `infra` 或 `interfaces`。
- 不得修改只读参考工程，不得在源码、测试、文档、配置或日志中泄露外部来源名称、路径或品牌。
- 不引入依赖注入框架、全局 Settings Proxy、全局服务定位器或模块级可变依赖容器。
- 每个任务遵循测试先行，并在独立验证通过后提交。
- 当前全项目 Pyright 基线为 184 个错误；新增配置与架构模块必须零错误，且全项目错误数不得增加。

---

## File Responsibility Map

| 文件或目录 | 单一职责 |
| --- | --- |
| `src/domain/__init__.py` | 标识纯业务层包；第一阶段不承载实现 |
| `src/application/__init__.py` | 标识用例编排层包；第一阶段不承载实现 |
| `src/infra/config/schema.py` | 定义不可变、严格校验的全部运行配置模型 |
| `src/infra/config/loader.py` | 将一个 TOML 文件纯函数式加载为 `AppConfig` |
| `src/infra/config/watcher.py` | 监视配置修订并执行准备—提交两阶段热更新 |
| `src/interfaces/bootstrap.py` | 暴露新架构组合根，加载配置并调用迁移期旧运行时 |
| `src/interfaces/__init__.py` | 标识外部接入层包 |
| `src/flow_agent/**` | 迁移期旧业务实现；除配置消费者外不改业务边界 |
| `tests/architecture/import_graph.py` | 构建静态内部导入图、查找循环和违规依赖 |
| `tests/architecture/test_source_layout.py` | 验证 `src` 包根和四层包可导入 |
| `tests/architecture/test_project_dependencies.py` | 对真实项目执行无环和四层依赖检查 |
| `tests/infra/config/test_schema.py` | 验证配置默认值、不可变性和跨字段约束 |
| `tests/infra/config/test_loader.py` | 验证单一 TOML 加载、未知字段和配置源约束 |
| `tests/infra/config/test_watcher.py` | 验证两阶段提交、失败清理和修订去重 |
| `config.example.toml` | 提供不含凭据的新配置结构示例 |

---

### Task 1: Move the Existing Package Under `src/` and Add Four-Layer Skeleton

**Files:**
- Create: `tests/architecture/test_source_layout.py`
- Create: `tests/architecture/__init__.py`
- Move: `flow_agent/` → `src/flow_agent/`
- Create: `src/domain/__init__.py`
- Create: `src/application/__init__.py`
- Create: `src/infra/__init__.py`
- Create: `src/interfaces/__init__.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: 当前 `flow_agent` 包和 `flow_agent.main:main` CLI 入口。
- Produces: 可从 `src` 解析的 `flow_agent`、`domain`、`application`、`infra`、`interfaces` 五个迁移期包；后续任务使用 `infra.config`。

- [ ] **Step 1: Write the failing source-layout test**

```python
from importlib.util import find_spec
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"


def test_python_packages_resolve_from_src():
    for package_name in (
        "flow_agent",
        "domain",
        "application",
        "infra",
        "interfaces",
    ):
        spec = find_spec(package_name)
        assert spec is not None
        locations = list(spec.submodule_search_locations or ())
        assert locations
        assert Path(locations[0]).resolve().is_relative_to(SOURCE_ROOT.resolve())


def test_legacy_package_no_longer_lives_at_repository_root():
    assert not (PROJECT_ROOT / "flow_agent").exists()
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `.venv/bin/python -m pytest tests/architecture/test_source_layout.py -q`

Expected: FAIL because `src/` and the four new layer packages do not exist.

- [ ] **Step 3: Move the package and create the layer markers**

Run the mechanical move:

```bash
mkdir -p src
git mv flow_agent src/flow_agent
```

Create each new `__init__.py` with only a Chinese package docstring. For example:

```python
"""基础设施层：实现应用端口与运行时技术能力。"""
```

Use corresponding descriptions for Domain、Application and Interfaces; do not add registries or side effects.

- [ ] **Step 4: Point Setuptools and Pytest at `src`**

Update `pyproject.toml` to contain:

```toml
[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
include = ["flow_agent*", "domain*", "application*", "infra*", "interfaces*"]
exclude = ["docker*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Keep `[project.scripts] flow-agent = "flow_agent.main:main"` for this phase.

- [ ] **Step 5: Verify imports and behavior**

Run:

```bash
.venv/bin/python -m pytest tests/architecture/test_source_layout.py -q
.venv/bin/python -c "import application, domain, flow_agent, infra, interfaces"
.venv/bin/python -m pytest -q
```

Expected: layout tests PASS, imports exit 0, full suite reports 238 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src tests/architecture
git commit -m "refactor: move Python packages under src"
```

---

### Task 2: Add a Reusable Static Import-Graph Analyzer

**Files:**
- Create: `tests/architecture/import_graph.py`
- Create: `tests/architecture/test_import_graph.py`

**Interfaces:**
- Consumes: 一个 Python 源码根目录和允许参与分析的顶层包名集合。
- Produces: `build_import_graph(source_root, package_roots) -> dict[str, set[str]]`、`find_import_cycles(graph) -> list[tuple[str, ...]]`、`find_forbidden_edges(graph, rules) -> list[tuple[str, str]]`。

- [ ] **Step 1: Write failing analyzer tests**

```python
from tests.architecture.import_graph import (
    build_import_graph,
    find_forbidden_edges,
    find_import_cycles,
)


def test_import_graph_finds_cycle(tmp_path):
    source = tmp_path / "src"
    package = source / "sample"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "a.py").write_text("from sample.b import value\n", encoding="utf-8")
    (package / "b.py").write_text("from sample.a import value\n", encoding="utf-8")

    graph = build_import_graph(source, {"sample"})

    assert find_import_cycles(graph) == [("sample.a", "sample.b")]


def test_import_graph_reports_forbidden_layer_edge(tmp_path):
    source = tmp_path / "src"
    domain = source / "domain"
    infra = source / "infra"
    domain.mkdir(parents=True)
    infra.mkdir(parents=True)
    (domain / "__init__.py").write_text("from infra import adapter\n", encoding="utf-8")
    (infra / "__init__.py").write_text("adapter = object()\n", encoding="utf-8")

    graph = build_import_graph(source, {"domain", "infra"})

    assert find_forbidden_edges(graph, {"domain": {"infra"}}) == [
        ("domain", "infra")
    ]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/architecture/test_import_graph.py -q`

Expected: FAIL because `tests.architecture.import_graph` does not exist.

- [ ] **Step 3: Implement exact analyzer interfaces**

Implement AST parsing without importing project modules:

```python
from __future__ import annotations

import ast
from pathlib import Path
from typing import Mapping


ImportGraph = dict[str, set[str]]


def build_import_graph(
    source_root: Path,
    package_roots: set[str],
) -> ImportGraph:
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
            imported_names: list[str] = []
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_from_import(source, path, node)
                if base:
                    imported_names.append(base)
                    imported_names.extend(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            for imported in imported_names:
                if imported.split(".", 1)[0] not in package_roots:
                    continue
                target = _resolve_module(imported, modules)
                if target is not None and target != source:
                    graph[source].add(target)
    return graph


def _resolve_module(name: str, modules: Mapping[str, Path]) -> str | None:
    candidate = name
    while candidate:
        if candidate in modules:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def _resolve_from_import(
    source: str,
    path: Path,
    node: ast.ImportFrom,
) -> str:
    if node.level == 0:
        return node.module or ""
    package_parts = source.split(".")
    if path.name != "__init__.py":
        package_parts.pop()
    for _ in range(node.level - 1):
        if package_parts:
            package_parts.pop()
    if node.module:
        package_parts.extend(node.module.split("."))
    return ".".join(package_parts)
```

Implement `find_import_cycles` with Tarjan strongly connected components and return only components whose size is greater than one, sorting both modules and components. Implement `find_forbidden_edges` by comparing each source and target top-level package with the passed `dict[str, set[str]]`, returning sorted unique full module pairs such as `("domain.order", "infra.sqlite")`.

- [ ] **Step 4: Run analyzer tests**

Run: `.venv/bin/python -m pytest tests/architecture/test_import_graph.py -q`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/architecture/import_graph.py tests/architecture/test_import_graph.py
git commit -m "test: add static import graph analyzer"
```

---

### Task 3: Define the Immutable Configuration Schema

**Files:**
- Create: `src/infra/config/__init__.py`
- Create: `src/infra/config/schema.py`
- Create: `tests/infra/__init__.py`
- Create: `tests/infra/config/__init__.py`
- Create: `tests/infra/config/test_schema.py`

**Interfaces:**
- Consumes: 直接对应新 `config.toml` 的嵌套映射。
- Produces: `AppConfig`、`MainModelConfig`、`ModelEndpointConfig` 和各运行单元配置类型；所有类型不可变且拒绝未知字段。

- [ ] **Step 1: Write failing schema tests**

```python
import pytest
from pydantic import ValidationError

from infra.config.schema import AppConfig


def minimal_config() -> dict[str, object]:
    return {
        "llm": {
            "main": {
                "model": "model-main",
                "api_key": "secret",
                "base_url": "https://example.test/v1",
            }
        }
    }


def test_app_config_is_frozen_and_rejects_unknown_fields():
    config = AppConfig.model_validate(minimal_config())
    with pytest.raises(ValidationError):
        config.jobs.max_workers = 8
    raw = minimal_config()
    raw["unknown"] = True
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_app_config_validates_cross_field_rules():
    raw = minimal_config()
    raw["channels"] = {"telegram_enabled": True}
    with pytest.raises(ValidationError, match="Telegram"):
        AppConfig.model_validate(raw)

    raw = minimal_config()
    raw["proactive"] = {
        "enabled": True,
        "target_user_id": "",
        "min_interval_seconds": 60,
        "max_interval_seconds": 30,
    }
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_app_config_uses_stable_defaults():
    config = AppConfig.model_validate(minimal_config())
    assert config.jobs.max_workers == 4
    assert config.jobs.max_queue_size == 64
    assert config.memory.enabled is True
    assert config.tooling.max_steps == 5
    assert config.channels.telegram_allowed_users == ()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/infra/config/test_schema.py -q`

Expected: FAIL because `infra.config.schema` does not exist.

- [ ] **Step 3: Implement the strict base and model connection types**

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

- [ ] **Step 4: Implement all configuration sections with exact names and defaults**

Use the following field contract; numeric bounds are enforced with `Field`:

| Type | Fields and defaults |
| --- | --- |
| `EmbeddingConfig` | `provider="qwen"`, `model="text-embedding-v3"`, `api_key=None`, `base_url=None` |
| `StorageConfig` | `memory_db_path=".flow/data/memory.db"`, `outbox_recovery_window_seconds=0.0 (ge=0)`, `outbox_recovery_limit=100 (ge=1)` |
| `LoggingConfig` | `level="INFO"` |
| `SessionConfig` | `default_id="default"`, `max_history_messages=500 (ge=1)`, `cache_size=64 (ge=1)`, `undo_enabled=True`, `tool_result_max_chars=10000 (ge=100)` |
| `ToolingConfig` | `enabled=True`, `max_steps=5 (ge=1)`, `selection_limit=8 (ge=1)` |
| `McpConfig` | `enabled=True`, `startup_timeout_seconds=30.0 (ge=1)`, `call_timeout_seconds=60.0 (ge=1)` |
| `RetrievalConfig` | `enabled=True`, `max_items=5 (ge=1)`, `min_score=0.18 (ge=0, le=1)` |
| `ObservabilityConfig` | `enabled=True`, `trace_path=".flow/logs/trace.jsonl"` |
| `MemoryConfig` | `enabled=True`, `max_messages=100 (ge=1)`, `deduplicate=True`, `consolidation_min_messages=5 (ge=1)`, `recent_turn_limit=8 (ge=1)`, `optimizer_enabled=True`, `optimizer_interval_seconds=64800 (ge=1)` |
| `ProactiveConfig` | `enabled=False`, `target_user_id=None`, `max_per_day=10 (ge=1)`, `min_interval_seconds=60.0 (ge=1)`, `max_interval_seconds=600.0 (ge=1)`, `cooldown_seconds=60.0 (ge=0)`, `judge_model=None`, `hawkes_enabled=True`, `hawkes_base_intensity=2.0 (ge=0)`, `hawkes_excitation_alpha=0.5 (ge=0)`, `hawkes_decay_beta=0.1 (ge=0)`, `hawkes_time_constant_seconds=30.0 (ge=1)`, `idle_enabled=False`, `idle_threshold_minutes=120.0 (ge=1)`, `interest_topics=()`, `state_path=".flow/data/proactive.db"`, `trace_path=".flow/logs/proactive.jsonl"` |
| `DriftConfig` | `enabled=True`, `data_dir=".flow/drift"`, `min_interval_hours=24.0 (ge=0.1)`, `max_steps=50 (ge=1)` |
| `ChannelsConfig` | `dashboard_enabled=False`, `dashboard_host="127.0.0.1"`, `dashboard_port=9901`, `http_enabled=False`, `http_host="127.0.0.1"`, `http_port=8788`, `telegram_enabled=False`, `telegram_bot_token=None`, `telegram_allowed_users=()`, `telegram_allowed_groups=()`；两个允许列表均为 `tuple[str, ...]` |
| `JobsConfig` | `max_queue_size=64 (ge=1)`, `max_workers=4 (ge=1)`, `shutdown_timeout_seconds=30.0 (gt=0)` |
| `DelegationConfig` | `enabled=True`, `max_concurrency=2 (ge=1)`, `tasks_file=".flow/sessions/subagent_tasks.jsonl"`, `max_local_chars=500 (ge=100)` |
| `PersonaConfig` | `name="FlowAgent"`, `passive_tone="professional, concise, helpful"`, `proactive_tone="friendly, brief, actionable"`, `style="structured"` |
| `PromptConfig` | `max_chars=8000 (ge=2000)`、`history_chars=3000 (ge=500)`、`memory_chars=1500 (ge=200)`、`tool_trace_chars=1000 (ge=200)` |

`ChannelsConfig` 使用 `model_validator(mode="after")` 验证启用 Telegram 时 `telegram_bot_token` 和 `telegram_allowed_users` 非空。`ProactiveConfig` 验证启用时 `target_user_id` 非空且最小间隔不大于最大间隔。

- [ ] **Step 5: Implement the top-level schema**

```python
class AppConfig(FrozenConfig):
    llm: LLMConfig
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    tooling: ToolingConfig = Field(default_factory=ToolingConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    delegation: DelegationConfig = Field(default_factory=DelegationConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
```

Export `AppConfig` and configuration section types from `infra.config.__init__` without importing Loader or Watcher.

- [ ] **Step 6: Run schema tests and scoped type check**

Run:

```bash
.venv/bin/python -m pytest tests/infra/config/test_schema.py -q
.venv/bin/python -m pyright --pythonpath .venv/bin/python src/infra/config/schema.py tests/infra/config/test_schema.py
```

Expected: schema tests PASS and scoped Pyright reports 0 errors.

- [ ] **Step 7: Commit**

```bash
git add src/infra/config tests/infra
git commit -m "feat: add immutable application configuration schema"
```

---

### Task 4: Load Exactly One TOML File Directly Into the Schema

**Files:**
- Create: `src/infra/config/loader.py`
- Create: `tests/infra/config/test_loader.py`
- Create: `config.example.toml`
- Modify: `.gitignore`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `pathlib.Path` pointing to one TOML file and `AppConfig.model_validate`。
- Produces: `load_config(path: Path) -> AppConfig`；不缓存、不查找备用路径、不读取环境变量。

- [ ] **Step 1: Write failing loader tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from infra.config.loader import load_config


def write_config(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_load_config_maps_toml_directly(tmp_path: Path):
    path = tmp_path / "config.toml"
    write_config(
        path,
        """
[llm.main]
model = "main-model"
api_key = "secret"

[channels]
telegram_enabled = true
telegram_bot_token = "token"
telegram_allowed_users = ["user-1"]

[jobs]
max_workers = 3
""".strip(),
    )

    config = load_config(path)

    assert config.llm.main.model == "main-model"
    assert config.channels.telegram_allowed_users == ("user-1",)
    assert config.jobs.max_workers == 3


def test_load_config_does_not_read_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FLOW_AGENT_LLM_MAIN_API_KEY", "environment-secret")
    path = tmp_path / "config.toml"
    write_config(path, '[llm.main]\nmodel = "main-model"\n')

    with pytest.raises(ValidationError):
        load_config(path)


def test_load_config_requires_existing_toml_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/infra/config/test_loader.py -q`

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

Do not add cache, environment fallback, YAML support, project-root discovery or LLM-specific Builders.

- [ ] **Step 4: Add the Python 3.10 dependency and safe example**

Add to project dependencies:

```toml
"tomli>=2.0; python_version < '3.11'",
```

Change `.gitignore` from ignoring both configuration files to:

```gitignore
config.toml
!config.example.toml
```

Create `config.example.toml` with `[llm.main]`、`[llm.fast]`、`[llm.vision]`、`[embedding]`、`[channels]`、`[proactive]`、`[jobs]` and `[delegation]` sections. Use empty credential strings only in the example and Chinese comments explaining required fields; never copy local credentials.

- [ ] **Step 5: Run loader tests and compile the example**

Run:

```bash
.venv/bin/python -m pytest tests/infra/config/test_loader.py -q
.venv/bin/python -c "from pathlib import Path; from infra.config.loader import load_config; load_config(Path('config.example.toml'))"
```

Expected: tests PASS and example loading exits 0. The example must provide non-empty placeholder strings such as `replace-me` for required values while containing no real credential format.

- [ ] **Step 6: Commit**

```bash
git add .gitignore pyproject.toml config.example.toml src/infra/config/loader.py tests/infra/config/test_loader.py
git commit -m "feat: load application config from one TOML source"
```

---

### Task 5: Implement Two-Phase Configuration Reloading

**Files:**
- Create: `src/infra/config/watcher.py`
- Create: `tests/infra/config/test_watcher.py`

**Interfaces:**
- Consumes: `AppConfig` current snapshot、`load_config`、one or more `ConfigApplier` implementations。
- Produces: `PreparedConfigChange(commit, discard)`、`ConfigApplier.prepare(current, candidate)`、`ConfigWatcher.reload_once() -> bool`、idempotent `start()` and `stop()`。

- [ ] **Step 1: Write failing two-phase tests**

```python
from pathlib import Path

from infra.config.schema import AppConfig
from infra.config.watcher import ConfigWatcher, PreparedConfigChange


def config(model: str) -> AppConfig:
    return AppConfig.model_validate(
        {"llm": {"main": {"model": model, "api_key": "secret"}}}
    )


def test_reload_commits_only_after_every_prepare_succeeds(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("revision-one", encoding="utf-8")
    commits: list[str] = []

    class Applier:
        def __init__(self, name: str) -> None:
            self.name = name

        def prepare(self, current: AppConfig, candidate: AppConfig):
            return PreparedConfigChange(
                commit=lambda: commits.append(self.name),
                discard=lambda: None,
            )

    watcher = ConfigWatcher(
        path,
        current=config("old"),
        appliers=(Applier("first"), Applier("second")),
        loader=lambda _: config("new"),
    )
    path.write_text("revision-two-longer", encoding="utf-8")

    assert watcher.reload_once() is True
    assert commits == ["first", "second"]
    assert watcher.current.llm.main.model == "new"


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
    path.write_text("revision-two-longer", encoding="utf-8")

    assert watcher.reload_once() is False
    assert actions == ["discard"]
    assert watcher.current is old
    assert watcher.reload_once() is False
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/infra/config/test_watcher.py -q`

Expected: FAIL because `infra.config.watcher` does not exist.

- [ ] **Step 3: Implement the two-phase data contracts**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

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

- [ ] **Step 4: Implement deterministic reload and thread lifecycle**

`ConfigWatcher.__init__` accepts `path`、`current`、`appliers`、`loader=load_config` and `interval_seconds=1.0`. `reload_once` must:

1. Compute `(st_mtime_ns, st_size)`.
2. Return `False` when the revision equals the committed or failed revision.
3. Load the candidate; Loader/Schema validation failure records the failed revision and returns `False` without calling any Applier.
4. Prepare appliers in order.
5. On Prepare failure, call `discard` in reverse order, record failed revision and return `False`.
6. Call every prepared `commit` in order; Commit callbacks are contractually non-failing assignments/reference swaps.
7. Replace `current`, record committed revision, clear failed revision and return `True`.

Expose the active snapshot through a read-only `current: AppConfig` property. Initialize the committed revision from the file revision observed during construction, so a newly constructed Watcher does not reapply the same file until it changes.

`start` uses one daemon thread named `runtime-config-watcher`; `stop` is idempotent and joins for at most three seconds. Thread exceptions are logged in Chinese and never terminate the service process.

- [ ] **Step 5: Run watcher tests and scoped checks**

Run:

```bash
.venv/bin/python -m pytest tests/infra/config/test_watcher.py -q
.venv/bin/python -m pyright --pythonpath .venv/bin/python src/infra/config tests/infra/config
```

Expected: watcher tests PASS and scoped Pyright reports 0 errors.

- [ ] **Step 6: Commit**

```bash
git add src/infra/config/watcher.py tests/infra/config/test_watcher.py
git commit -m "feat: add two-phase runtime config reload"
```

---

### Task 6: Migrate Runtime Consumers and Delete the Legacy Configuration Cycle

**Files:**
- Create: `src/interfaces/bootstrap.py`
- Create: `src/interfaces/cli.py`
- Modify: `pyproject.toml`
- Modify: `src/flow_agent/main.py`
- Modify: `src/flow_agent/app/bootstrap.py`
- Modify: `src/flow_agent/core/agent.py`
- Modify: `src/flow_agent/llm/client.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_message_bus_architecture.py`
- Modify: `tests/test_passive_turn_concurrency.py`
- Modify: `tests/test_telegram_multimodal.py`
- Replace: `tests/test_config.py`
- Delete: `tests/test_config_watcher.py`
- Delete: `src/flow_agent/config/__init__.py`
- Delete: `src/flow_agent/config/settings.py`
- Delete: `src/flow_agent/config/loader.py`
- Delete: `src/flow_agent/config/source_values.py`
- Delete: `src/flow_agent/config/watcher.py`
- Delete: `src/flow_agent/llm/config.py`

**Interfaces:**
- Consumes: `load_config(Path) -> AppConfig`、`AppConfig` section types and existing runtime factories。
- Produces: `interfaces.bootstrap.load_application_config(project_root: Path) -> AppConfig`、`interfaces.cli.main(argv: Sequence[str] | None = None) -> int`、`flow_agent.main.run_service(config: AppConfig) -> None`、`flow_agent.app.bootstrap.create_app_runtime(config: AppConfig)`、接收 `system_prompt: str` 的 `Agent`、接收 `ModelEndpointConfig` 的 `OpenAILLMClient`。

- [ ] **Step 1: Write failing explicit-injection tests**

Replace legacy config tests with assertions against new public interfaces:

```python
import ast
from pathlib import Path

from infra.config.schema import AppConfig
from interfaces.bootstrap import load_application_config


def test_bootstrap_loads_explicit_project_config(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        '[llm.main]\nmodel = "main"\napi_key = "secret"\n',
        encoding="utf-8",
    )

    config = load_application_config(tmp_path)

    assert isinstance(config, AppConfig)
    assert config.llm.main.model == "main"


def test_runtime_code_does_not_use_global_settings_proxy():
    source_root = Path(__file__).parents[1] / "src"
    offenders: list[str] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "settings":
                offenders.append(str(path.relative_to(source_root)))
    assert offenders == []
```

Update Agent unit tests to construct it with `system_prompt="system"` instead of a Settings object. Update LLM client construction tests to pass `config.llm.main`.

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_config.py tests/test_agent.py -q
```

Expected: FAIL because `interfaces.bootstrap` and explicit constructor signatures do not exist.

- [ ] **Step 3: Add the new composition-root entry**

```python
from pathlib import Path

from infra.config.loader import load_config
from infra.config.schema import AppConfig


def load_application_config(project_root: Path) -> AppConfig:
    """从项目唯一配置文件加载启动快照。"""

    return load_config(project_root / "config.toml")
```

Do not import `flow_agent.app.bootstrap` at module import time in this file; keep loading testable without constructing network clients.

Create `interfaces.cli` as the actual command entry. It owns argument parsing and workspace initialization; when no subcommand is selected, it loads `AppConfig` and calls `flow_agent.main.run_service(config)`. Change the script entry to:

```toml
[project.scripts]
flow-agent = "interfaces.cli:main"
```

Remove argument parsing from `flow_agent.main`; that module becomes a migration-period runtime adapter and must not import Interfaces.

- [ ] **Step 4: Narrow Agent and LLM client configuration dependencies**

Change Agent constructor from `settings: Settings` to `system_prompt: str` and replace both `self.settings.system_prompt` reads with `self.system_prompt`.

Change OpenAI client constructor to:

```python
def __init__(
    self,
    config: ModelEndpointConfig,
) -> None:
    if not config.api_key:
        raise ValueError("API key is required")
    self.model = config.model
    self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    self.async_client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
    )
```

Create separate `ModelEndpointConfig` values in Bootstrap for main、fast and vision rather than using override arguments.

- [ ] **Step 5: Make all runtime factories explicit**

Use these exact interface signatures:

```text
create_core_components(config: AppConfig) -> dict[str, object]
create_message_bus(config: AppConfig) -> MessageBus
def create_passive_turn_pipeline(
    *,
    config: AppConfig,
    agent: Agent,
    tool_registry: ToolRegistry,
    message_bus: MessageBus,
    event_bus: EventBus,
    memory_engine: MemoryEngine | None = None,
    markdown_store=None,
    recorder=None,
    phase_modules_provider=None,
    tool_hook_executor=None,
) -> PassiveTurnPipeline
create_app_runtime(config: AppConfig) -> tuple[object, ...]
```

Load configuration once in `interfaces.cli.main`, pass it through `flow_agent.main.run_service(config)` to `create_app_runtime(config)`, and pass only section values to downstream constructors. Replace `settings.get()` in every factory. Keep the existing return tuple in Phase 1; the named `ApplicationRuntime` arrives in a later migration plan because changing it now expands scope beyond configuration.

- [ ] **Step 6: Connect the new watcher without a global cache**

Create a Bootstrap-local `ConfigApplier` whose `prepare` validates all hot fields and returns a prepared change. The Commit callback may only assign validated primitive fields or atomically replace references:

```python
def commit_runtime_patch() -> None:
    apply_runtime_settings(candidate)


return PreparedConfigChange(
    commit=commit_runtime_patch,
    discard=lambda: None,
)
```

Instantiate:

```python
ConfigWatcher(
    PROJECT_ROOT / "config.toml",
    current=config,
    appliers=(runtime_config_applier,),
)
```

Do not expose Watcher state through a module global.

- [ ] **Step 7: Update tests and remove legacy modules**

Replace imports from `flow_agent.config.settings` with `infra.config.schema`. Remove tests for `ConfigValues` and Settings Cache; keep or strengthen behavior tests for defaults, validation, successful reload and Prepare failure cleanup. Delete the six legacy configuration files listed above only after `rg -n 'flow_agent\.config|flow_agent\.llm\.config' src tests` returns no consumers.

- [ ] **Step 8: Run focused and full regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_config.py tests/infra/config/test_watcher.py tests/test_agent.py tests/test_message_bus_architecture.py tests/test_passive_turn_concurrency.py tests/test_telegram_multimodal.py -q
.venv/bin/python -m pytest -q
```

Expected: focused tests PASS and full suite reports at least 238 tests with no failures; obsolete config-helper tests may be replaced only by stronger schema、Loader and Watcher tests.

- [ ] **Step 9: Commit**

```bash
git add src tests
git commit -m "refactor: inject config through the composition root"
```

---

### Task 7: Enforce Project Dependency Rules and Complete Phase Verification

**Files:**
- Create: `tests/architecture/test_project_dependencies.py`
- Modify: `scripts/verify.sh`
- Modify: `tests/test_ci_verification.py`
- Modify: `docs/specs/2026-08-01-ddd-refactor/requirements.md`
- Modify: `docs/specs/2026-08-01-ddd-refactor/design.md`
- Modify: `docs/specs/2026-08-01-ddd-refactor/tasks.md`

**Interfaces:**
- Consumes: `tests.architecture.import_graph` and the real `src` source tree。
- Produces: CI-enforced zero-cycle and four-layer dependency gates；第一阶段验证证据和规格状态。

- [ ] **Step 1: Write failing real-project architecture tests**

```python
from pathlib import Path

from tests.architecture.import_graph import (
    build_import_graph,
    find_forbidden_edges,
    find_import_cycles,
)


SOURCE_ROOT = Path(__file__).parents[2] / "src"
PACKAGE_ROOTS = {"flow_agent", "domain", "application", "infra", "interfaces"}


def test_project_internal_import_graph_has_no_cycles():
    graph = build_import_graph(SOURCE_ROOT, PACKAGE_ROOTS)
    assert find_import_cycles(graph) == []


def test_four_layers_only_use_allowed_dependency_directions():
    graph = build_import_graph(SOURCE_ROOT, PACKAGE_ROOTS)
    forbidden = {
        "domain": {"application", "infra", "interfaces"},
        "application": {"infra", "interfaces"},
    }
    assert find_forbidden_edges(graph, forbidden) == []


def test_only_composition_root_may_import_infra_from_interfaces():
    graph = build_import_graph(SOURCE_ROOT, PACKAGE_ROOTS)
    violations = sorted(
        (source, target)
        for source, targets in graph.items()
        for target in targets
        if source.startswith("interfaces.")
        and source != "interfaces.bootstrap"
        and target.split(".", 1)[0] == "infra"
    )
    assert violations == []


def test_legacy_code_does_not_import_interfaces():
    graph = build_import_graph(SOURCE_ROOT, PACKAGE_ROOTS)
    forbidden = {"flow_agent": {"interfaces"}}
    offenders = find_forbidden_edges(graph, forbidden)
    assert offenders == []
```

The migration-period exception allows `flow_agent` to import `infra.config` until its modules move into the four layers, but never allows it to import Interfaces.

- [ ] **Step 2: Run the architecture tests**

Run: `.venv/bin/python -m pytest tests/architecture/test_project_dependencies.py -q`

Expected: PASS after Task 6 removed the known configuration cycle. If any cycle remains, print the exact strongly connected component and fix the dependency rather than suppressing it.

- [ ] **Step 3: Update the verification script for `src`**

Change compilation and isolation checks to:

```bash
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

"${PYTHON_BIN}" -m compileall -q src

if rg -n -i 'akashic[-_ ]?agent|/home/roco/akashic-agent|参考项目|参考仓库' src tests; then
    echo "检测到不应出现在当前项目中的参考来源信息"
    exit 1
fi
```

Extend `tests/test_ci_verification.py` to assert `compileall -q src` and the architecture test directory are exercised by default Pytest collection.

- [ ] **Step 4: Run all completion checks**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pyright --pythonpath .venv/bin/python src/infra/config tests/architecture tests/infra/config
.venv/bin/python -m black --check --fast --target-version py310 src tests
phase1_pyright_output="$(mktemp)"
.venv/bin/python -m pyright --pythonpath .venv/bin/python >"${phase1_pyright_output}" 2>&1 || true
phase1_pyright_errors="$(rg -o '[0-9]+ errors?' "${phase1_pyright_output}" | tail -1 | awk '{print $1}')"
test "${phase1_pyright_errors}" -le 184
bash scripts/verify.sh
rg -n -i 'akashic[-_ ]?agent|/home/roco/akashic-agent|参考项目|参考仓库' src tests
git diff --check
git status --short
```

Expected:

- Full Pytest has no failures and all prior product behavior remains covered.
- Scoped Pyright reports 0 errors; full-project Pyright count does not exceed the recorded baseline of 184.
- Black check, verify script and whitespace check pass.
- Source isolation scan prints no matches.
- Status contains only Phase 1 files and the intentionally uncommitted `.superpowers/` preview directory if it still exists.

- [ ] **Step 5: Record evidence and mark Phase 1 verified**

Update specification statuses from `已确认` to `已验证` only after all commands pass. Add a verification section to `requirements.md` containing the exact Pytest total, scoped Pyright result, import-cycle result and commit hashes. Check every completed box in this plan; do not pre-check unfinished steps.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify.sh tests/test_ci_verification.py tests/architecture docs/specs/2026-08-01-ddd-refactor
git commit -m "test: enforce DDD architecture boundaries"
```
