# 被动回合并发与会话隔离：任务清单

- 状态：已验证
- 对应需求：requirements.md
- 对应设计：design.md

## 预期修改文件

- 修改：flow_agent/core/agent_loop.py
- 修改：flow_agent/core/passive_turn_pipeline.py
- 修改：flow_agent/core/agent.py
- 修改：flow_agent/llm/client.py
- 修改：flow_agent/llm/router.py
- 修改：flow_agent/tools/registry.py
- 测试：tests/test_passive_turn_concurrency.py
- 测试：tests/test_agent_loop.py
- 测试：tests/test_llm_async.py

## 任务

### 任务 1：建立并发与隔离的失败测试

- [x] 编写两个不同 session 的可控异步管道测试。
- [x] 断言第二回合可在第一回合释放前开始。
- [x] 编写同 session FIFO 回归测试。
- [x] 编写会话历史隔离测试。
- [x] 运行测试并确认主循环缺少异步管道入口。

### 任务 2：建立异步模型接口

- [x] 为模型客户端定义 async generate 接口。
- [x] 实现网络调用的取消传播与异常映射。
- [x] 为测试客户端提供可控异步实现。
- [x] 运行模型接口测试。

### 任务 3：消除 Agent 的隐式会话状态依赖

- [x] 写出显式 session_id 历史读取的失败测试。
- [x] 让消息构建和回合提交显式接收 session_id。
- [x] 移除被动回合对 agent.set_session 的依赖。
- [x] 运行会话隔离测试。

### 任务 4：异步化被动管道和工具循环

- [x] 将阶段执行、模型调用和工具循环改为 awaitable。
- [x] 为同步工具定义受控单步边界和取消语义。
- [x] 保持 TurnCommitted 先于出站投递的顺序。
- [x] 运行被动回合与消息总线集成测试。

### 任务 5：适配主循环与兼容入口

- [x] 让 _process_async 等待异步管道。
- [x] 保持同 session owner 和 FIFO 队列行为。
- [x] 为 run_once 保留无运行事件循环下的同步入口。
- [x] 覆盖停止、取消和后续消息恢复。

### 任务 6：完整验证

- [x] 运行新增测试和相关被动链路测试；全量测试被既有缺失模块阻塞。
- [x] 运行语法、差异检查和工作区扫描。
- [ ] 更新本文件状态和验证记录。

## 当前验证记录

- pytest tests/test_passive_turn_concurrency.py tests/test_reliable_delivery.py tests/test_phase3_boundaries.py -q：21 项通过。
- 当前异步入口保持同步管道兼容回退；真实并发依赖任务 2 与任务 4 完成。

## 最终验证记录

- pytest tests/test_passive_turn_concurrency.py tests/test_agent.py tests/test_plugin_pipeline_integration.py tests/test_llm_streaming.py tests/test_phase3_boundaries.py tests/test_reliable_delivery.py -q：34 项通过。
- 全量测试收集被既有缺失模块阻塞：channels.channel_bootstrap、proactive.modules、ops、dashboard、eval、marketplace。
