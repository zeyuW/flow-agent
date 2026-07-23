# Agent 稳定性与自动化改造记录

日期：2026-07-23

## 一、问题概览

今天集中处理了五类问题：

1. Telegram 出现大量重复消息。
2. Agent 停止后重新启动，历史消息集中按当前时间发送。
3. 英文新闻没有按中文偏好翻译。
4. 出站消息恢复策略与 IM 离线消息语义不一致。
5. 缺少自动测试、自动提交说明、自动提交和 CI 流程。

## 二、重复消息的原因

程序启动时原本会读取本地出站数据库中 prepared、sending、failed 状态的消息，并重新放入发送队列。

此前 Telegram 发送失败的消息一直保留在本地数据库中。程序再次启动后，这些历史消息被集中重发，所以出现了大量重复内容。

启动日志曾出现：

    已恢复 42 条未确认出站消息

这说明重复消息主要来自历史出站记录恢复，不是模型思考过程泄露。

Telegram 显示的时间是实际调用 Telegram API 的时间。历史消息被重新发送后，自然会显示为当前时间。

## 三、出站恢复策略

当前策略已经调整为：

- Agent 启动时默认不恢复历史出站消息；
- prepared 和 failed 历史记录标记为 expired；
- sending 状态转为 unknown；
- unknown 禁止自动重放；
- 运行期间只对明确可重试的失败进行有限退避重试；
- 单条消息过期只影响自身，不影响其他消息。

默认配置：

    [storage]
    outbox_recovery_window_seconds = 0
    outbox_recovery_limit = 100

如果确实需要短暂异常重启恢复消息，可以显式设置：

    [storage]
    outbox_recovery_window_seconds = 300

表示只恢复最近 5 分钟的消息。

## 四、IM 离线消息语义

### Agent 故障

如果消息在持久化之前 Agent 就故障，数据库中没有消息记录：

    没有持久化记录 → 不补发 → 用户收不到

这是正常故障语义。

### Agent 正常、手机 Telegram 离线

如果 Agent 正常调用 Telegram API：

    Agent 发送
    → Telegram 服务端接收并保存
    → 手机 Telegram 上线
    → 客户端拉取离线消息

此时 Telegram 服务端会保留原始发送时间，手机端会显示类似“昨天 15:30”的历史时间。

这不应该依赖 Agent 本地 outbox 重放。

### Agent 到 Telegram API 网络失败

这属于 Agent 出站失败，不等同于手机离线：

- 运行期间进行有限即时重试；
- 可重试网络错误进入退避重试；
- unknown 禁止自动重试，避免重复发送；
- Agent 重启时默认不恢复历史失败消息。

本地 created_at 仅用于诊断，不能修改 Telegram UI 的服务端时间。

## 五、出站状态

    prepared
    已持久化，尚未开始发送。

    sending
    正在调用渠道发送接口。

    delivered
    渠道确认送达。

    failed
    明确失败，可根据策略在运行期间重试。

    unknown
    结果不确定，禁止自动重放。

    expired
    超出恢复或运行期重试窗口，不再发送。

主要实现：

- flow_agent/messaging/outbox.py
- flow_agent/messaging/message_bus.py
- flow_agent/app/bootstrap.py

## 六、用户偏好与英文新闻

Agent 可以记住用户偏好，例如使用中文、关注科技和 AI、希望主动推送。但“使用中文回复”只约束回复语言，不一定要求翻译外部新闻内容。

而且已经写入 outbox 的历史消息属于最终文本，恢复时不会重新调用模型，所以历史英文消息不会自动翻译。

主动新闻链路后续应明确执行：

    如果外部内容不是中文：
        翻译标题和摘要
        再生成最终消息
        再进入出站队列

推荐拆分偏好：

    response_language = zh-CN
    translate_external_content = true
    preserve_original_title = false

## 七、今天完成的开发阶段

### 阶段一：事件总线生命周期

- 增加事件订阅和取消订阅；
- 完善生命周期管理；
- 增加回归测试。

提交：

    4783bff feat: 完善事件总线生命周期管理

### 阶段二：上下文与任务恢复

- 增加上下文持久化；
- 增加任务状态持久化；
- 增加错误分类；
- 增加重试与恢复语义；
- 补充状态恢复测试。

提交：

    acd2db8 feat: 增加上下文持久化与任务恢复能力

### 阶段三：出站可靠投递

- 增加 SQLite 出站持久化；
- 增加稳定投递 ID和幂等判断；
- 增加历史消息过期策略；
- 增加运行期间退避重试；
- 增加 unknown、expired 状态；
- 补充重复投递和恢复测试；
- 增加出站配置项。

提交：

    2aa5af4 feat: 完善出站消息可靠投递与恢复策略
    6d71478 feat: 完善出站消息可靠投递与恢复策略

### 阶段四：自动化流程

- 增加统一验证脚本；
- 增加按阶段提交脚本；
- Agent 自动生成提交标题和改动要点；
- 增加提交前检查；
- 更新 GitHub Actions CI；
- 增加 Draft PR 发布流程。

提交：

    8be8e1f chore: 建立自动验证提交与 CI 流程
    427eb1b chore: 建立自动验证提交与 CI 流程
    586f17a chore: 建立自动验证提交与 CI 流程

## 八、测试结果

今天完成的相关测试：

    事件总线测试：3 passed
    状态恢复测试：5 passed
    出站可靠投递及边界测试：34 passed
    自动化流程验证测试：14 passed
    出站相关测试最终结果：18 passed

统一验证入口：

    scripts/verify.sh

按阶段提交入口：

    scripts/submit_phase.sh phase1
    scripts/submit_phase.sh phase2
    scripts/submit_phase.sh phase3
    scripts/submit_phase.sh automation

提交并推送：

    scripts/submit_phase.sh --push phase3

提交说明由 Agent 自动生成，例如：

    feat: 完善出站消息可靠投递策略

    增加运行期退避重试
    禁止启动时恢复历史失败消息
    补充出站投递回归测试

## 九、GitHub 发布

发布分支：

    agent/reliable-delivery-and-automation

Draft PR：

    https://github.com/zeyuW/flow-agent/pull/1

目标分支：

    main

PR 已包含四阶段变更说明、问题原因、解决方案、测试结果和 CI 配置。

## 十、后续工作

1. 完善主动新闻翻译规则。
2. 增加出站状态诊断命令，统计 delivered、failed、unknown、expired。
3. 为主动推送、被动回复和后台任务使用不同幂等键。
4. 增加 Telegram API 失败场景的集成测试。
5. PR CI 通过后合并到 main。
6. 检查 .flow/data/outbound_messages.db，确认旧积压已变为 expired。
