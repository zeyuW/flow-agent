# 统一 IM 渠道适配层实施计划

> **执行说明：** 本计划基于 `docs/specs/2026-08-09-unified-channel-adapters/design.md`，按任务逐项执行。每个任务先写失败测试，再实现最小代码，最后运行对应验证。

**目标：** 将 `interfaces/channels` 重构为配置驱动的统一 IM 适配层，使新增平台只需要一个适配器文件、一次注册和一个配置块。

**架构：** `base.py` 提供唯一渠道协议和通用生命周期，`service.py` 负责注册、配置装配、启动、停止和线程回收。各平台文件只处理自己的协议细节；`ServiceApp` 只依赖 `ChannelService`，`application` 只依赖通用消息地址，不再读取 Telegram 或 QQ 专属路由字段。

**技术栈：** Python 3.14 运行环境、Python 3.11+ 代码约束、dataclasses、typing.Protocol、Pydantic、asyncio、threading、pytest、uv。

## 全局约束

- 所有新增和修改的项目文档使用中文；代码标识符、命令、路径和第三方专有名词保持原样。
- 不保留 `interfaces.channels.protocol`、`interfaces.channels.models` 的长期兼容转发层。
- 不保留旧的 `telegram_enabled`、`telegram_bot_token`、`telegram_allowed_users` 等平台专属全局配置字段。
- `ServiceApp` 不直接导入 `TelegramChannel`、`QQChannel`、`QQBotChannel` 或其他具体渠道类。
- `application` 不导入 `interfaces.channels` 的具体平台模块，也不构造 `telegram_chat_id`、`qq_user_id`、`qq_group_id` 路由字段。
- `infra.bus` 是唯一消息总线；不得在 `interfaces/channels` 下新增第二套消息队列或总线。
- 渠道生命周期边界使用同步 `start()`、`stop()`、`join()`；异步事件循环必须由具体适配器自己封装。
- 每个行为变更必须先有能够失败的测试，再实现生产代码。
- 测试统一使用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，避免 ROS 环境插件污染 pytest。

---

## 任务一：建立渠道协议和服务的失败测试

**文件：**

- 新增：`backend/tests/interfaces/test_channel_contract.py`
- 新增：`backend/tests/interfaces/test_channel_service.py`
- 新增：`backend/tests/interfaces/test_channel_normalization.py`

**接口：**

- 消费：设计文档中的 `ChannelAdapter`、`ChannelContext`、`ChannelService` 和通用消息地址。
- 产出：能够约束基类行为、注册行为、启动回滚、逆序停止、消息规范化的失败测试。

- [ ] **步骤 1：编写基类生命周期失败测试**

创建一个 `FakeChannel`，测试以下行为：

```python
def test_base_channel_subscribes_and_unsubscribes_outbound_callback(tmp_path: Path):
    bus = RecordingBus()
    channel = FakeChannel()
    logger = logging.getLogger("test-channel")

    channel.start(ChannelContext(bus=bus, event_bus=FakeEventBus(), log=logger, attachment_dir=tmp_path))
    assert bus.subscribed == ["fake"]
    assert channel.status().running is True

    channel.stop()
    assert bus.unsubscribed == ["fake"]
    assert channel.status().running is False
```

同时验证重复 `start()` 和重复 `stop()` 不会重复订阅或抛出异常，`join()` 能够回收适配器创建的 worker。

- [ ] **步骤 2：编写服务注册和构造失败测试**

覆盖以下行为：

```python
def test_channel_service_builds_only_enabled_channels():
    service = ChannelService()
    service.register("fake", lambda options, context: FakeChannel(options))
    service.build_enabled(
        ChannelsConfig(adapters={"fake": {"enabled": True}, "off": {"enabled": False}}),
        context,
    )
    assert [adapter.name for adapter in service.adapters()] == ["fake"]


def test_channel_service_rejects_duplicate_registration():
    service = ChannelService()
    service.register("fake", factory)
    with pytest.raises(ValueError, match="fake"):
        service.register("fake", factory)
```

再测试某个渠道构造或启动失败时，已经启动的渠道按照逆序停止。

- [ ] **步骤 3：编写通用消息规范化失败测试**

测试适配器调用 `publish_inbound()` 后得到的 `InboundMessage` 包含正确的
`channel`、`session_id`、`chat_id`、`sender`、`text`、`media` 和 `metadata`；测试
`SendMessage.recipient_id` 最终成为出站消息的 `chat_id`。

- [ ] **步骤 4：运行测试确认失败**

运行：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q \
  tests/interfaces/test_channel_contract.py \
  tests/interfaces/test_channel_service.py \
  tests/interfaces/test_channel_normalization.py
```

预期：测试失败，原因是新的协议、服务和规范化字段尚未实现，而不是测试导入错误。

---

## 任务二：实现统一渠道基类和通用消息地址

**文件：**

- 修改：`backend/src/interfaces/channels/base.py`
- 修改：`backend/src/interfaces/channels/__init__.py`
- 删除：`backend/src/interfaces/channels/protocol.py`
- 删除：`backend/src/interfaces/channels/models.py`
- 修改：`backend/src/application/conversation/domain/channel_message.py`
- 修改：`backend/src/application/conversation/domain/messages.py`
- 修改：`backend/src/application/conversation/app/phase.py`

**接口：**

- 消费：任务一中的失败测试。
- 产出：`ChannelCapabilities`、`ChannelContext`、`ChannelStatus`、`ChannelAdapter`、`BaseChannelAdapter`，以及带 `chat_id` 的统一消息模型。

- [ ] **步骤 1：实现公共数据类型和协议**

在 `base.py` 中实现：

```python
@dataclass(frozen=True, slots=True)
class ChannelCapabilities:
    text: bool = True
    file: bool = False
    image: bool = False
    streaming: bool = False
```

同时实现 `ChannelContext`、`ChannelStatus` 和 `ChannelAdapter`，所有生命周期方法使用同步签名。

- [ ] **步骤 2：实现 `BaseChannelAdapter`**

实现以下公共行为：

- `start(context)` 保存上下文、订阅出站回调、调用 `_start_platform()`；
- `stop()` 先停止入口、取消出站订阅、调用 `_stop_platform()`；
- `join(timeout)` 等待内部 worker；
- `on_outbound(message)` 调用 `_deliver_outbound(message)`；
- `send_file()` 和 `send_image()` 默认返回不可重试的不支持结果；
- `publish_inbound()` 构造统一的 `InboundMessage` 并发布到 `MessageBus`。

生命周期方法必须幂等，平台 hook 抛错时更新 `_last_error` 并恢复到停止状态。

- [ ] **步骤 3：给消息领域模型增加通用 `chat_id`**

在 `InboundMessage` 和 `IncomingMessage` 增加 `chat_id: str`，在 `TurnFlow` 增加 `chat_id`。更新 `ChatWorker`、`PassiveTurnPipeline` 和相关构造调用，使消息从入站渠道到对话流程始终携带通用目标。

- [ ] **步骤 4：收敛公开导出并删除重复模块**

`interfaces.channels.__init__` 只导出新的基类、状态、能力、上下文和消息类型。删除 `protocol.py`、`models.py`，同步修改测试中对这两个旧模块的导入。

- [ ] **步骤 5：运行基类和规范化测试确认通过**

运行：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q \
  tests/interfaces/test_channel_contract.py \
  tests/interfaces/test_channel_normalization.py
```

预期：新增测试通过；具体平台测试暂时可能失败，原因仅限于平台类仍使用旧协议。

---

## 任务三：实现配置驱动的 `ChannelService`

**文件：**

- 新增：`backend/src/interfaces/channels/service.py`
- 修改：`backend/src/infra/config.py`
- 新增：`backend/tests/interfaces/test_channel_configuration.py`
- 修改：`backend/tests/infrastructure/test_schema.py`

**接口：**

- 消费：`ChannelAdapter`、`ChannelContext`、`AppConfig`。
- 产出：`ChannelService.register()`、`build_enabled()`、`start_all()`、`stop_all()`、`join_all()`，以及动态渠道配置。

- [ ] **步骤 1：编写动态配置失败测试**

测试下面的 TOML 数据可以被解析为按名称分组的渠道配置：

```python
raw["channels"] = {
    "telegram": {"enabled": True, "bot_token": "secret"},
    "feishu": {"enabled": False, "app_id": "id"},
}
config = AppConfig.model_validate(raw)
assert config.channels.adapters["telegram"]["bot_token"] == "secret"
```

测试配置中不存在具体平台字段的假设，并测试每个渠道只接收自己的选项。

- [ ] **步骤 2：实现 `ChannelsConfig` 动态映射**

将平台专属平铺字段替换为 `adapters: dict[str, dict[str, object]]`。公共字段只保留每个渠道的 `enabled`；配置模型不得为 Telegram、QQ 或未来平台添加字段。

- [ ] **步骤 3：实现注册和实例化**

在 `ChannelService` 中维护名称到工厂的映射，拒绝重复注册。注册内置适配器：`cli`、`http`、`qq`、`qqbot`、`telegram`。构造实例时传入单个平台配置和同一个 `ChannelContext`。

- [ ] **步骤 4：实现统一生命周期和失败回滚**

`start_all()` 记录启动顺序，某个适配器失败时逆序停止已启动实例；`stop_all()` 继续停止所有实例；`join_all()` 对每个适配器传递剩余超时并记录超时实例。

- [ ] **步骤 5：运行配置和服务测试确认通过**

运行：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q \
  tests/interfaces/test_channel_service.py \
  tests/interfaces/test_channel_configuration.py \
  tests/infrastructure/test_schema.py
```

---

## 任务四：迁移 CLI、HTTP 和 QQ 适配器

**文件：**

- 修改：`backend/src/interfaces/channels/cli.py`
- 修改：`backend/src/interfaces/channels/http.py`
- 修改：`backend/src/interfaces/channels/qq.py`
- 修改：`backend/src/interfaces/channels/qqbot.py`
- 修改：`backend/tests/interfaces/test_chunked_decoder.py`
- 新增：`backend/tests/interfaces/test_channel_adapters.py`

**接口：**

- 消费：`BaseChannelAdapter` 和 `ChannelService`。
- 产出：四个适配器都能使用统一的 `start/stop/join/status`，并通过通用 `chat_id` 发布和投递消息。

- [ ] **步骤 1：为适配器迁移补充失败测试**

测试 CLI 入站消息发布通用 `chat_id`，HTTP 和 OneBot Webhook 使用统一入站构造，QQ 出站使用 `OutboundMessage.chat_id` 而不是平台元数据分支。测试 QQ 官方 Bot 的名称为 `qqbot`，不覆盖 `qq` 注册名。

- [ ] **步骤 2：迁移 CLI 和 HTTP**

让 `CLIChannel` 和 `HTTPChannel` 继承 `BaseChannelAdapter`。保留 stdin/stdout 和 HTTP Webhook 的平台行为，只删除各自的订阅、状态和重复生命周期代码。

- [ ] **步骤 3：迁移 OneBot QQ**

让 `QQChannel` 继承基类，保留 Chunked 请求解析、私聊过滤、Access Token 和 `send_private_msg`。入站使用基类的 `publish_inbound()`，出站从通用 `message.chat_id` 取目标。

- [ ] **步骤 4：迁移 QQ 官方 Bot**

让 `QQBotChannel` 继承基类，保留 WebSocket 握手、心跳、断线重连、事件解析和官方 HTTP API。将 `name` 固定为 `qqbot`，内部异步任务由适配器自己管理，`ServiceApp` 不再创建其事件循环。

- [ ] **步骤 5：运行适配器测试确认通过**

运行：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q \
  tests/interfaces/test_chunked_decoder.py \
  tests/interfaces/test_channel_adapters.py \
  tests/integration/test_conversation_delivery_contracts.py
```

---

## 任务五：迁移 Telegram 适配器并统一媒体能力

**文件：**

- 修改：`backend/src/interfaces/channels/telegram.py`
- 修改：`backend/src/interfaces/channels/common.py`
- 修改：`backend/tests/interfaces/test_telegram_multimodal.py`
- 修改：`backend/tests/interfaces/test_telegram_security.py`
- 修改：`backend/tests/integration/test_telegram_conversation_flow.py`

**接口：**

- 消费：`BaseChannelAdapter`、通用 `ChannelContext` 和 `ChannelDeliveryResult`。
- 产出：Telegram 的轮询、媒体、流式事件和主动推送都在一个适配器内部工作。

- [ ] **步骤 1：先调整 Telegram 契约测试**

将测试中的上下文注入和出站回调改为新的同步渠道边界；继续保留图片下载、图片文档、图片发送、长文本切片和 Token 日志脱敏断言。

- [ ] **步骤 2：迁移 Telegram 生命周期**

让 Telegram 适配器继承 `BaseChannelAdapter`。适配器内部创建自己的 asyncio 事件循环线程；`start()` 创建线程并返回，`stop()` 向内部事件循环提交停止协程，`join()` 等待线程。

- [ ] **步骤 3：迁移 Telegram 入站规范化**

保留私聊/群聊白名单、图片和图片文档下载、媒体路径校验和流式事件订阅。入站统一设置 `session_id`、`chat_id`、`sender_id`，Telegram 细节只进入 `metadata`。

- [ ] **步骤 4：迁移 Telegram 出站和主动推送能力**

让 `_deliver_outbound()` 使用 `message.chat_id`，让 `send_text`、`send_file`、`send_image` 返回标准投递结果。保留 Telegram 的长消息分片、流式消息编辑和思考消息清理。

- [ ] **步骤 5：运行 Telegram 测试确认通过**

运行：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q \
  tests/interfaces/test_telegram_multimodal.py \
  tests/interfaces/test_telegram_security.py \
  tests/integration/test_telegram_conversation_flow.py
```

---

## 任务六：清理应用层和组合根的平台专属依赖

**文件：**

- 修改：`backend/src/application/conversation/app/pipeline.py`
- 修改：`backend/src/application/proactive/app/deliver.py`
- 修改：`backend/src/application/scheduling/app/runtime.py`
- 修改：`backend/src/application/delegation/app/manager.py`
- 修改：`backend/src/infra/bus/message.py`
- 修改：`backend/src/bootstrap/service_app.py`
- 修改：`backend/src/bootstrap/container.py`
- 修改：`backend/src/application/capabilities/tools/message_push.py`
- 修改：`backend/tests/conversation/test_chat_worker.py`
- 修改：`backend/tests/conversation/test_passive_turn_concurrency.py`
- 修改：`backend/tests/integration/test_conversation_delivery_contracts.py`
- 修改：`backend/tests/proactive/test_proactive_source_ack.py`
- 修改：`backend/tests/scheduling/test_scheduler_tasks.py`
- 修改：`backend/tests/delegation/test_spawn_runtime.py`
- 新增：`backend/tests/architecture/test_channel_boundaries.py`

**接口：**

- 消费：`ChannelService.adapters()` 和 `TurnFlow.chat_id`。
- 产出：业务层和 `ServiceApp` 不再出现具体渠道导入或平台路由分支。

- [ ] **步骤 1：为平台字段泄漏编写失败架构测试**

测试 `application` 和 `bootstrap.service_app` 的源代码中不出现具体渠道模块导入；测试业务代码不出现 `telegram_chat_id`、`qq_user_id`、`qq_group_id` 以及 `if channel == "telegram"` 路由分支。

- [ ] **步骤 2：清理 `MessageBus` 的平台目标解析**

让 `SendMessage.recipient_id` 直接生成 `OutboundMessage.chat_id`。删除按 Telegram、QQ 分支读取元数据的逻辑，保留非渠道消息总线行为和投递可靠性。

- [ ] **步骤 3：清理对话管道的通用目标路由**

使用 `flow.chat_id` 构造被动回复、错误回复、思考事件和 `message_push` 的目标。保留所有平台元数据，但不再用它们决定投递地址。

- [ ] **步骤 4：清理主动、调度和委托路由**

主动消息、定时消息和委托完成消息只设置通用 `channel`、`conversation_id`、`recipient_id` 和公共元数据，不再为 Telegram 或 QQ 写特殊键。

- [ ] **步骤 5：改造 `ServiceApp` 和工具注册**

删除 `_telegram`、`_http`、Telegram 专用线程和 Telegram 专用停止函数。初始化时创建一个 `ChannelService`，启动时调用 `start_all()`，停止时调用 `stop_all()` 和 `join_all()`。把所有启用适配器的发送能力注册到 `MessagePushTool`，不再手写 Telegram 注册分支。

- [ ] **步骤 6：运行架构和集成测试确认通过**

运行：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q \
  tests/architecture \
  tests/integration \
  tests/conversation \
  tests/proactive \
  tests/scheduling \
  tests/delegation
```

---

## 任务七：删除旧结构、补齐文档并完成全量验证

**文件：**

- 修改：`backend/README.md`
- 修改：根目录 `README.md`
- 修改：`docs/specs/README.md`
- 修改：`backend/tests/architecture/test_channel_boundaries.py`
- 修改：`backend/tests/architecture/test_project_dependencies.py`

**接口：**

- 消费：完成后的 `ChannelService` 和新的配置结构。
- 产出：正式文档、配置示例、架构测试和全量验证结果。

- [ ] **步骤 1：扫描旧导入和旧配置**

运行：

```bash
rg -n "interfaces\.channels\.(protocol|models)|telegram_enabled|telegram_bot_token|telegram_chat_id|qq_user_id|qq_group_id|from interfaces\.channels\.(telegram|qq|qqbot|http|cli)" \
  backend/src backend/tests README.md backend/README.md scripts --glob '*.py' --glob '*.toml' --glob '*.md' --glob '*.sh'
```

只允许平台适配器内部出现平台协议字段；旧协议模块和 `ServiceApp` 具体平台导入不得有结果。

- [ ] **步骤 2：更新配置示例和目录说明**

将 `config.example.toml` 改为 `[channels.<name>]` 配置块，更新两个 README 的渠道架构、注册流程、生命周期和新增适配器说明，所有新增说明使用中文。

- [ ] **步骤 3：运行格式和编译检查**

运行：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m black --check src tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m compileall -q src tests
```

- [ ] **步骤 4：运行完整后端测试**

运行：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q
```

预期：所有测试通过，且没有 ROS pytest 插件导入错误。

- [ ] **步骤 5：验证启动脚本和架构边界**

运行：

```bash
bash -n scripts/start.sh
rg -n "python -m bootstrap\.main|interfaces\.channels\.service" scripts backend/src/bootstrap
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q tests/architecture tests/infrastructure/test_service_app_lifecycle.py
```

预期：启动脚本语法通过，组合根只使用渠道服务，生命周期和架构测试通过。
