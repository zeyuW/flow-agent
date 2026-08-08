# Unified IM Channel Adapters Design

## Status

Approved direction; implementation is the next phase.

## Goal

Rebuild `backend/src/interfaces/channels` as the single IM access layer for
Flow Agent. Every platform-specific integration must implement one stable
channel contract, while the application and infrastructure layers consume
only normalized messages and delivery results.

Adding a new platform such as Feishu, WeChat, Discord, or DingTalk must require
only:

1. one platform adapter file;
2. one registration entry;
3. one platform configuration block.

No application use case, conversation pipeline, message bus implementation, or
`ServiceApp` platform-specific branch may be required.

## Scope

This change covers:

- the channel directory layout and public exports;
- one channel protocol and one lifecycle model;
- configuration-driven channel registration and construction;
- normalized inbound and outbound addressing;
- migration of CLI, HTTP, OneBot QQ, official QQ Bot, and Telegram;
- generic registration of message-push capabilities;
- removal of platform-specific routing from application code;
- contract, registry, lifecycle, adapter, and architecture tests.

This change does not add new Feishu or WeChat API implementations. Their
adapter files may be represented by registration tests or a minimal fixture,
but real provider API work remains a separate feature.

## Design principles

### 1. Channels are transport adapters, not business handlers

The channel layer parses provider payloads, authenticates provider requests,
downloads provider attachments, sends provider replies, and translates
provider failures. It publishes normalized inbound messages to `infra.bus` and
consumes normalized outbound messages from it.

The channel layer does not create agent runs, execute conversation use cases,
select models, manage memory, or implement proactive/scheduled business
policy. Those responsibilities remain in `application`.

This follows the useful boundary in DeerFlow: a platform base class owns the
channel contract, each provider has its own module, and a service coordinates
the configured providers. Flow Agent keeps its existing `infra.bus` instead of
creating a second channel-local bus.

### 2. The application uses generic addressing

The normalized message concepts are:

- `channel`: provider key such as `telegram`, `qq`, or `feishu`;
- `session_id`: Flow Agent's logical conversation key;
- `chat_id`: provider conversation identifier used to reply to the same chat;
- `sender_id`: provider sender identifier;
- `recipient_id`: outbound target identifier;
- `metadata`: provider extension data that is not needed by application logic.

`telegram_chat_id`, `qq_user_id`, and `qq_group_id` are adapter metadata, not
application routing fields. The adapter creates generic `chat_id` and
`sender_id` values while preserving provider details only in `metadata`.

`InboundMessage` and `IncomingMessage` gain a first-class generic `chat_id`.
`TurnFlow` carries that value through the conversation pipeline. Outbound
construction uses `chat_id`/`recipient_id` directly and no longer searches for
provider-specific metadata keys.

### 3. The lifecycle boundary is synchronous

`ServiceApp` has a synchronous `init()`, `start()`, `wait()`, and `stop()`
lifecycle. The channel service follows the same boundary:

```python
channel_service.start_all()
channel_service.stop_all()
channel_service.join_all(timeout=8.0)
```

An adapter may use an internal asyncio loop, worker thread, HTTP server, or
WebSocket task. That implementation detail is private to the adapter file.
This removes the Telegram-only event-loop handling from `ServiceApp` and lets
all channels participate in the same stop-and-join sequence.

## Target directory

```text
backend/src/interfaces/channels/
├── __init__.py       # Stable public exports for the channel package
├── base.py           # Protocol, context, status, capabilities, base adapter
├── service.py        # Registry, config construction, start/stop/join
├── common.py         # Small reusable attachment/HTTP helpers only
├── cli.py            # stdin/stdout adapter
├── http.py           # Generic inbound HTTP adapter
├── qq.py             # OneBot-compatible QQ adapter
├── qqbot.py          # Official QQ Bot WebSocket adapter
├── telegram.py       # Telegram Bot API adapter
├── feishu.py         # Future Feishu adapter entry point
└── wechat.py         # Future WeChat adapter entry point
```

`protocol.py`, `models.py`, and the duplicate channel declarations in
`base.py` are removed. The stable public channel types come from `base.py` and
`__init__.py`. The current unused `SessionIdentityIndex` and `MessageDeduper`
helpers are removed rather than retained as speculative abstractions.

`common.py` remains only when a helper is genuinely shared by at least two
adapters. Provider-specific helpers stay in the provider file, so a new
adapter remains understandable as one unit.

## Core channel contract

`base.py` defines these public types:

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

`BaseChannelAdapter` supplies the common implementation. Its public lifecycle
is idempotent and it owns the outbound subscription. Subclasses implement only
platform hooks such as `_start_platform`, `_stop_platform`, inbound event
parsing, and `_deliver_outbound`.

Unsupported media operations return a non-retryable
`ChannelDeliveryResult` rather than raising an implementation-specific
exception. Provider network failures are translated to retryable or uncertain
results; `infra.bus` remains responsible for retry policy.

The base class also exposes a single inbound helper that requires generic
arguments:

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

This prevents each adapter from constructing subtly different domain
messages.

## Channel service and registration

`service.py` contains the registry and lifecycle coordinator. Its factory
boundary is:

```python
ChannelFactory = Callable[
    [Mapping[str, object], ChannelContext],
    ChannelAdapter,
]
```

The service provides:

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

Built-in adapters are registered in one central registration function inside
`service.py`. The bootstrap layer calls that function but never imports a
provider module. Duplicate channel names are rejected during registration;
the OneBot QQ adapter and official QQ Bot adapter therefore use distinct keys
(`qq` and `qqbot`).

`build_enabled` creates only configured adapters. A construction failure names
the channel and aborts initialization before any background service starts.
`start_all` starts adapters in registration order. If one start fails, already
started adapters are stopped in reverse order. `stop_all` always uses reverse
order and continues stopping remaining adapters after logging an individual
failure. `join_all` waits for every adapter worker and reports threads that
remain alive after the timeout.

## Configuration

The flat platform-specific fields in `ChannelsConfig` are replaced with a
generic map of named channel settings. The TOML shape is:

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

The configuration loader preserves each nested channel block as a mapping.
The channel factory owns validation of provider-specific options, while the
global configuration model validates only the common `enabled` flag and
mapping shape. This means adding `channels.feishu` does not require changing
the global Pydantic model.

The adapter factory receives only its own options. Secrets are never included
in status output or exception logs.

## Message bus changes

The channel layer continues to use `infra.bus.MessageBus` as the sole message
transport. The bus callback type is widened from a `None`-only callback to a
callback that may return `ChannelDeliveryResult`; the dispatcher treats a
missing result as a successful legacy-style callback only during the migration
of non-channel subscribers, while all new adapters return an explicit result.

The bus's chat-target resolution becomes generic: `SendMessage.recipient_id`
is copied to the outbound `chat_id`, and `metadata` is not inspected for
Telegram or QQ keys. This makes scheduled, proactive, delegated, and passive
replies use the same routing path.

## Application changes

The conversation pipeline changes from provider-specific metadata lookup to
generic `TurnFlow.chat_id` routing. Message-push registration receives the
enabled adapter collection from bootstrap and registers capabilities by
adapter name; it does not import a concrete adapter.

Proactive delivery, scheduled delivery, delegation completion, error replies,
and streaming events use generic `channel` and `chat_id` values. No application
module may branch on a provider name for routing or construct a provider-
specific metadata key.

Platform-specific formatting, Markdown conversion, message chunking, typing
indicators, stream edits, and media upload behavior remain in the adapter that
owns the provider API.

## Adapter migration rules

- `TelegramChannel` keeps polling, allowed-user/group checks, image download,
  long-message splitting, stream edit/delete behavior, and Bot API calls in
  `telegram.py`.
- `QQChannel` keeps OneBot HTTP webhook parsing and private-message delivery in
  `qq.py`.
- `QQBotChannel` keeps official Bot WebSocket handshake, heartbeat, reconnect,
  event parsing, and HTTP sending in `qqbot.py`.
- `CLIChannel` and `HTTPChannel` implement the same base contract even though
  they are not IM providers, so `ServiceApp` has one lifecycle path.
- Existing tests are updated to assert generic `chat_id` and `recipient_id`
  semantics. Provider tests continue to assert provider protocol behavior
  inside the provider module.

## Error handling and shutdown

Inbound parse/auth failures are handled at the adapter boundary and never
publish malformed messages. Temporary provider failures update
`ChannelStatus.last_error` and return retryable delivery results. Permanent
authentication, validation, and unsupported-capability errors return
non-retryable results.

On process shutdown:

1. `ServiceApp.stop()` signals global shutdown.
2. `ChannelService.stop_all()` stops ingress and unsubscribes outbound
   callbacks in reverse order.
3. Other application runtimes stop.
4. `ChannelService.join_all()` waits for provider worker threads/tasks.
5. `ServiceApp` releases the process lock and exits.

An adapter must not leave a non-daemon worker, open provider connection, or
message-bus subscription after `join()` returns.

## Verification

Tests are added or updated in:

- `backend/tests/interfaces/test_channel_contract.py` for base behavior;
- `backend/tests/interfaces/test_channel_service.py` for registration,
  configuration, startup rollback, reverse shutdown, and joining;
- `backend/tests/interfaces/test_channel_normalization.py` for generic
  inbound/outbound addressing;
- existing provider tests for Telegram, QQ, HTTP, and chunked payloads;
- `backend/tests/architecture/test_channel_boundaries.py` for import and
  platform-key leakage rules;
- lifecycle and integration tests for `ServiceApp` and message delivery.

Required verification command:

```bash
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m pytest -q
```

The architecture tests must also prove that bootstrap imports only
`interfaces.channels.service`, and that `application` contains no imports of
concrete channel modules.
