# 被动回合停机取消：任务清单

- 状态：已验证
- 对应需求：requirements.md
- 对应设计：design.md

## 文件清单

- 修改：flow_agent/core/agent_loop.py
- 修改：tests/test_reliable_delivery.py

## 任务

### 任务 1：为取消语义建立回归测试

- [x] 新增挂起被动回合场景。
- [x] 确认修复前测试因主循环等待挂起回合而失败。
- [x] 断言回合清理逻辑执行且活跃任务数归零。

### 任务 2：收束活跃回合

- [x] 在主循环清理分支获取活跃任务快照。
- [x] 取消快照中的未完成任务。
- [x] 等待任务收束，并保留既有异常隔离行为。
- [x] 运行相关测试与语法、空白检查。

## 验证记录

- pytest tests/test_reliable_delivery.py tests/test_phase3_boundaries.py -q：19 项通过。
- python -m py_compile flow_agent/core/agent_loop.py：通过。
- git diff --check：通过。
