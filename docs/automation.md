# 自动开发流水线

Agent 完成代码后，调用 scripts/agent_finish.sh 并传入本次修改文件，例如：

    scripts/agent_finish.sh flow_agent/xxx.py tests/test_xxx.py

脚本会自动完成：

1. 编译源码；
2. 检查空白、冲突标记和项目隔离；
3. 运行全部测试；
4. 检查暂存内容中的疑似密钥；
5. 根据修改范围生成提交说明；
6. 创建 Git 提交。

如果需要提交后自动推送并触发 CI：

    scripts/agent_finish.sh --push flow_agent/xxx.py tests/test_xxx.py

也可以设置：

    export FLOW_AGENT_AUTO_PUSH=1

由于当前工作区可能同时存在用户已有改动，必须由 Agent 显式传入本次修改文件，不能使用 git add -A。

启用手动提交前检查：

    scripts/install_hooks.sh


## Agent 自动生成提交说明

Agent 可以根据任务目标和实际修改自动生成标题与要点，再交给脚本完成验证和提交：

    scripts/agent_finish.sh --push       --summary "feat: 完善出站消息可靠投递策略"       --details $'增加运行期退避重试\n禁止启动时恢复历史失败消息\n补充出站投递回归测试'       flow_agent/messaging/message_bus.py       flow_agent/messaging/outbox.py       tests/test_reliable_delivery.py

用户不需要手动编写提交说明。未提供摘要时，脚本仍使用文件范围生成兜底说明。
