# 插件候选原子发布：任务清单

- 状态：实施中
- 对应需求：requirements.md
- 对应设计：design.md

## 文件清单

- 修改：`flow_agent/plugins/plugin_loader.py`，实行同轮候选先准备、后发布。
- 修改测试：`tests/test_plugin_runtime_system.py`。

## 任务

### 任务 1：同轮候选原子准备

- [x] 在 `tests/test_plugin_runtime_system.py` 写入失败测试：单轮协调中一个候选插件无效时，当前工具与后台 Job 保持不变。
- [x] 运行指定测试并确认旧实现先发布有效候选，测试失败。
- [x] 将加载器改为先准备全部变化候选，任一失败时清理所有未发布候选。
- [x] 验证候选失败、正常热更新与插件移除。

### 任务 2：完整验证与本地交付

- [ ] 将需求与任务验收项更新为实际状态和验证结果。
- [ ] 运行 `bash scripts/verify.sh`。
- [ ] 运行 `rg -n -i 'akashic[-_ ]?agent|/home/roco/akashic-agent|参考项目|参考仓库' flow-agent`、`git -C flow-agent diff --check` 和 `git -C flow-agent status --short`。
- [ ] 不提交、不推送；由用户决定后续版本控制操作。
