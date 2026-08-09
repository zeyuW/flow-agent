# 统一 IM 渠道适配层设计

## 文档状态

设计已确认并已完成实施；本文记录当前统一渠道适配层的结构和约束。

## 一、目标

将 `backend/src/interfaces/channels` 重构为 Flow Agent 统一的 IM 接入层。
所有平台适配器都实现同一套渠道协议，`application` 和 `infra` 只处理统一
消息模型和统一投递结果，不感知 Telegram、QQ、飞书、微信等平台的具体协议。

以后新增一个平台时，只需要完成以下三件事：

1. 新增一个平台适配器文件；
2. 在渠道目录注册一次；
3. 增加一个平台配置块。

不需要修改对话业务、消息总线、主动推送、定时任务或 `ServiceApp` 中的平台
分支。

## 二、范围

本次改造包含：

- 重整 `interfaces/channels` 目录和公开导出；
- 统一渠道协议、上下文、状态、能力和生命周期；
- 按配置注册和创建渠道实例；
- 统一入站、出站消息地址；
- 迁移 CLI、HTTP、OneBot QQ、QQ 官方 Bot 和 Telegram；
- 统一主动推送工具的渠道注册；
- 清理 `application` 中的平台专属路由判断；
- 增加协议、注册、生命周期、消息规范化和架构边界测试。

本次不实现真实的飞书或微信 API。可以增加最小适配器骨架或注册测试，真实
平台协议接入作为后续独立功能。

## 三、核心原则

### 3.1 渠道层只做协议适配

渠道层负责：

- 解析平台入站协议；
- 校验平台请求和访问权限；
- 下载平台附件；
- 调用平台 API 发送消息；
- 将平台异常转换为统一投递结果；
- 将平台消息转换为统一入站消息；
- 从消息总线接收统一出站消息。

渠道层不负责创建 Agent 运行、执行对话用例、选择模型、管理记忆、制定主动
推送策略或执行定时任务。这些职责继续留在 `application`。

DeerFlow 的可借鉴点是“基类 + 每个平台一个文件 + 服务统一管理”。本项目保留
这个边界，但继续使用已有的 `infra.bus`，不在渠道目录中重新实现一套消息总线。

### 3.2 业务层只使用通用消息地址

统一消息概念如下：

- `channel`：平台名称，例如 `telegram`、`qq`、`feishu`；
- `session_id`：Flow Agent 内部的逻辑会话标识；
- `chat_id`：平台会话标识，用于回复原会话；
- `sender_id`：平台发送者标识；
- `recipient_id`：出站消息目标标识；
- `metadata`：平台扩展信息，只允许适配器解释。

`telegram_chat_id`、`qq_user_id`、`qq_group_id` 等字段只能作为适配器内部的
平台元数据，不能作为 `application` 的路由依据。适配器必须生成通用的
`chat_id` 和 `sender_id`。

`InboundMessage` 和 `IncomingMessage` 增加一等的 `chat_id` 字段，`TurnFlow`
在对话管道中携带该字段。出站构造直接使用 `chat_id` 或 `recipient_id`，不再
扫描平台专属元数据。

### 3.3 渠道生命周期采用同步边界

`ServiceApp` 的生命周期是同步的：

```python
channel_service.start_all()
channel_service.stop_all()
channel_service.join_all(timeout=8.0)
```

适配器内部可以使用 asyncio 事件循环、线程、HTTP 服务或 WebSocket，但这些
实现细节必须封装在适配器文件中。这样 `ServiceApp` 不再为 Telegram 单独维护
事件循环和线程，所有渠道都能参与统一的停止和资源回收流程。

## 四、目标目录

```text
backend/src/interfaces/channels/
├── __init__.py       # 渠道包的稳定公开导出
├── base.py           # 协议、上下文、状态、能力和通用基类
├── service.py        # 注册、配置装配、启动、停止和等待
├── cli.py            # stdin/stdout 渠道适配器
├── http.py           # 通用 HTTP 渠道适配器
├── qq.py             # OneBot 兼容 QQ 适配器
├── qqbot.py          # QQ 官方 Bot WebSocket 适配器
├── telegram.py       # Telegram Bot API 适配器
├── feishu.py         # 后续飞书适配器入口
└── wechat.py         # 后续微信适配器入口
```

`protocol.py`、`models.py` 和 `base.py` 中重复的渠道声明会被移除，稳定公开
类型统一从 `base.py` 和 `__init__.py` 导出。

没有实际被多个适配器复用的工具不单独保留公共文件；平台专属工具留在对应
平台文件中，真正跨业务的技术能力放在顶层 `infra`。

## 五、核心渠道协议

`base.py` 定义以下公开类型：

```python
@dataclass(frozen=True, slots=True)
class ChannelCapabilities:
    text: bool = True
    file: bool = False
    image: bool = False
    streaming: bool = False


@dataclass(frozen=True, slots=True)
class ChannelContext:
    bus: MessageBus
    event_bus: EventBus
    log: logging.Logger
    attachment_dir: Path


@dataclass(frozen=True, slots=True)
class ChannelStatus:
    running: bool
    last_error: str | None = None


class ChannelAdapter(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> ChannelCapabilities: ...

    def start(self, context: ChannelContext) -> None: ...
    def stop(self) -> None: ...
    def join(self, timeout: float | None = None) -> None: ...
    def status(self) -> ChannelStatus: ...

    def send_text(
        self, *, recipient_id: str, text: str
    ) -> ChannelDeliveryResult: ...

    def send_file(
        self, *, recipient_id: str, path: str
    ) -> ChannelDeliveryResult: ...

    def send_image(
        self, *, recipient_id: str, path: str
    ) -> ChannelDeliveryResult: ...
```

`BaseChannelAdapter` 提供公共实现，负责：

- 保存 `MessageBus`、`EventBus`、日志和附件目录；
- 统一订阅和取消订阅出站消息；
- 维护运行状态和最后一次错误；
- 统一处理重复启动和重复停止；
- 将平台入站消息发布为 `InboundMessage`；
- 将 `OutboundMessage` 交给平台适配器发送。

平台适配器只实现 `_start_platform`、`_stop_platform`、平台事件解析和
`_deliver_outbound` 等平台相关行为。

不支持的文件或图片能力返回 `retryable=False` 的
`ChannelDeliveryResult`，不抛出平台自定义异常。网络异常转换为可重试或结果
未知的投递结果，重试策略由 `infra.bus` 统一负责。

基类提供统一的入站发布方法：

```python
publish_inbound(
    *,
    session_id: str,
    chat_id: str,
    sender_id: str,
    text: str,
    media: Sequence[str] = (),
    metadata: Mapping[str, object] | None = None,
) -> None
```

这样可以避免每个平台构造出不同形态的领域消息。

## 六、渠道服务和注册

`service.py` 同时负责渠道注册和生命周期协调，工厂类型为：

```python
ChannelFactory = Callable[
    [Mapping[str, object], ChannelContext],
    ChannelAdapter,
]
```

服务提供以下接口：

```python
class ChannelService:
    def register(self, name: str, factory: ChannelFactory) -> None: ...
    def build_enabled(
        self,
        configs: ChannelsConfig,
        context: ChannelContext,
    ) -> None: ...
    def start_all(self) -> None: ...
    def stop_all(self) -> None: ...
    def join_all(self, timeout: float | None = None) -> None: ...
    def adapters(self) -> tuple[ChannelAdapter, ...]: ...
```

内置适配器在 `service.py` 的统一注册函数中注册。`bootstrap` 只调用渠道服务
和注册函数，不直接导入 Telegram、QQ 或其他平台模块。

注册时拒绝重复名称。OneBot QQ 和 QQ 官方 Bot 使用不同的注册名：`qq` 和
`qqbot`，避免当前两个类都使用 `qq` 导致覆盖。

`build_enabled` 只创建配置中启用的适配器。构造失败时必须带上渠道名称，并在
任何后台服务启动前终止初始化。

`start_all` 按注册顺序启动。如果某个渠道启动失败，已启动的渠道按逆序停止。
`stop_all` 始终按逆序停止，并记录单个渠道的停止异常后继续停止其他渠道。
`join_all` 等待所有渠道线程或内部任务，并报告超时仍存活的线程。

## 七、配置结构

当前 `ChannelsConfig` 中的 `telegram_enabled`、`telegram_bot_token` 等扁平
字段改为按渠道名保存的动态配置。TOML 形态为：

```toml
[channels.telegram]
enabled = true
bot_token = "..."
allowed_users = ["..."]
allowed_groups = ["..."]

[channels.qq]
enabled = false
host = "127.0.0.1"
port = 8789
api_base = "http://127.0.0.1:5700"
```

配置加载器保留每个渠道块为独立映射。全局配置只校验公共的 `enabled` 字段
和映射结构；平台必填项由各自工厂校验。新增 `[channels.feishu]` 不需要修改
全局配置模型。

适配器工厂只能收到自己的配置选项。状态输出和异常日志不得包含密钥。

## 八、消息总线改造

渠道层继续使用 `infra.bus.MessageBus` 作为唯一消息传输设施，不在
`interfaces/channels` 下新增消息总线。

总线出站回调类型从“只能返回 `None`”扩展为“可以返回
`ChannelDeliveryResult`”。迁移期间，旧的无返回值回调仍被视为成功；所有新
渠道适配器必须返回明确的投递结果。

总线的目标解析改为通用规则：`SendMessage.recipient_id` 直接复制到出站消息的
`chat_id`，不再根据渠道名称读取 Telegram 或 QQ 元数据。主动消息、定时消息、
委托完成消息和被动回复统一使用同一条投递路径。

## 九、应用层改造

对话管道从平台元数据查找改为使用通用的 `TurnFlow.chat_id`。Bootstrap 将
启用的适配器集合注入消息推送工具，按适配器名称注册其文本、文件和图片能力，
但不导入任何具体平台类。

主动投递、定时投递、委托完成、错误回复和流式事件都使用通用的 `channel`、
`chat_id` 和 `recipient_id`。应用层禁止按平台名称分支路由，禁止构造平台专属
元数据键。

平台格式化、Markdown 转换、长文本分片、输入状态、流式编辑和媒体上传仍由
对应平台适配器负责。

## 十、现有适配器迁移规则

- `TelegramChannel` 继续在 `telegram.py` 中处理轮询、用户和群组白名单、图片
  下载、长消息切片、流式编辑/删除和 Bot API 调用。
- `QQChannel` 继续在 `qq.py` 中处理 OneBot HTTP Webhook 和私聊消息发送。
- `QQBotChannel` 继续在 `qqbot.py` 中处理官方 Bot WebSocket 握手、心跳、重连、
  事件解析和 HTTP 发送。
- `CLIChannel`、`HTTPChannel` 也实现同一套基类协议。它们虽然不是 IM 平台，
  但可以因此使用同一套生命周期。
- 现有测试改为断言通用的 `chat_id` 和 `recipient_id`；平台测试继续在平台
  文件边界内断言平台协议行为。

## 十一、错误处理和关闭

入站解析或鉴权失败必须在适配器边界处理，不得发布格式错误的消息。临时平台
故障更新 `ChannelStatus.last_error` 并返回可重试结果；认证、参数和能力不支持
等永久错误返回不可重试结果。

进程停止顺序为：

1. `ServiceApp.stop()` 发出全局停止信号；
2. `ChannelService.stop_all()` 停止入口并逆序取消出站订阅；
3. 其他应用运行时停止；
4. `ChannelService.join_all()` 等待渠道线程和任务退出；
5. `ServiceApp` 释放进程锁并退出。

适配器的 `join()` 返回后，不得留下非守护线程、平台连接或消息总线订阅。

## 十二、验证要求

新增或调整以下测试：

- `backend/tests/interfaces/test_channel_contract.py`：基类协议和公共行为；
- `backend/tests/interfaces/test_channel_service.py`：注册、配置、启动回滚、
  逆序停止和线程回收；
- `backend/tests/interfaces/test_channel_normalization.py`：通用入站和出站地址；
- 现有 Telegram、QQ、HTTP 和 Chunked 请求测试；
- `backend/tests/architecture/test_channel_boundaries.py`：导入边界和平台字段
  泄漏检查；
- `ServiceApp` 生命周期和消息投递集成测试。

完整验证命令：

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q
```

架构测试必须证明：

- `bootstrap` 只导入 `interfaces.channels.service`，不直接导入具体渠道；
- `application` 不导入任何具体渠道模块；
- 应用层不存在 `telegram_chat_id`、`qq_user_id`、`qq_group_id` 等平台路由键；
- 所有渠道都通过统一的 `ChannelService` 生命周期管理。
