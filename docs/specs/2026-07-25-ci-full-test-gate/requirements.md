# Requirements

## Goal

CI 和本地统一验证必须自动收集当前仓库中的全部 pytest 测试，新增 `tests/test_*.py` 文件无需维护白名单即可执行。

## Functional requirements

- `scripts/verify.sh` 默认使用 `pytest -q`，依赖 `pyproject.toml` 的 `testpaths = ["tests"]` 收集测试。
- `FLOW_AGENT_TEST_TARGET` 保留为开发者运行局部测试的显式覆盖入口，但 CI 不设置该变量。
- 不恢复已删除的 dashboard、旧主动模块、旧 ops/eval/marketplace 或旧 channel 组装层，仅为其编写的测试必须删除。
- 同时覆盖仍受支持功能的测试，若仅因已删除依赖而无法收集，则移除失效依赖与对应断言，保留其他有效测试。
- 手动验证脚本不得使用 `test_*.py` 名称；应保留在可追踪的 `manual/` 目录，避免 pytest 自动收集。
- GitHub Actions 继续调用 `scripts/verify.sh`，使本地和 CI 运行同一命令。

## Acceptance criteria

- 在干净检出环境中执行 `bash scripts/verify.sh` 成功。
- 新增一个符合 `test_*.py` 命名规则的测试文件时，默认 pytest 收集会包含它。
- CI 不再维护测试文件白名单。
