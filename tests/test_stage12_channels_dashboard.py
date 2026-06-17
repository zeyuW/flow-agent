import json
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

from flow_agent.channels.cli import CLIChannel
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.channels.http import HTTPChannel
from flow_agent.channels.qq import QQChannel
from flow_agent.dashboard.api import DashboardServer
from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.messaging.message_bus import MessageBus


class _FakeOutboundSub:
    def __init__(self):
        self.received: list[OutboundMessage] = []

    def on_outbound(self, message: OutboundMessage) -> None:
        self.received.append(message)


def test_cli_channel_handles_line():
    """CLI 渠道通过 MessageBus 发布入站消息。"""
    bus = MessageBus()
    cli = CLIChannel(message_bus=bus, default_session_id="s1")
    cli.start()

    # 发布消息
    cli.handle_line("hi")
    inbound = bus.consume_inbound()
    assert inbound is not None
    assert inbound.text == "hi"
    assert inbound.session_id == "s1"
    cli.stop()


def test_http_channel_inbound_roundtrip():
    """HTTP 渠道接收 POST，通过 MessageBus 发布入站消息。"""
    bus = MessageBus()
    http = HTTPChannel(host="127.0.0.1", port=0, message_bus=bus)
    http.start()
    port = http._server.server_address[1]  # type: ignore[union-attr]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/inbound",
        data=json.dumps({"session_id": "s1", "text": "ping"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    assert payload["ok"] is True
    assert payload["queued"] is True

    # 验证消息已入队
    inbound = bus.consume_inbound()
    assert inbound is not None
    assert inbound.text == "ping"
    http.stop()


def test_dashboard_server_snapshot():
    store = InMemoryDashboardStore()
    store.record({"type": "turn_start", "trace_id": "t1"})
    server = DashboardServer(host="127.0.0.1", port=0, store=store)
    server.start()
    port = server._server.server_address[1]  # type: ignore[union-attr]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/snapshot", timeout=2) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    assert "turns" in payload
    assert payload["turns"][-1]["type"] == "turn_start"
    server.stop()


def test_dashboard_server_ui_page():
    store = InMemoryDashboardStore()
    server = DashboardServer(host="127.0.0.1", port=0, store=store)
    server.start()
    port = server._server.server_address[1]  # type: ignore[union-attr]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/ui", timeout=2) as resp:
        body = resp.read().decode("utf-8")
        content_type = resp.headers.get("Content-Type", "")
    assert "text/html" in content_type
    assert "Flow Agent 功能控制台" in body
    assert "/runtime/quality" in body
    server.stop()


def test_qq_channel_private_message_roundtrip():
    """QQ 渠道通过 MessageBus 发布入站消息，并通过订阅接收出站。"""
    pushed: list[dict[str, object]] = []

    class QQApiHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            pushed.append(json.loads(raw.decode("utf-8")))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

    api_server = HTTPServer(("127.0.0.1", 0), QQApiHandler)
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()
    api_port = api_server.server_address[1]

    bus = MessageBus()
    qq = QQChannel(
        host="127.0.0.1",
        port=0,
        message_bus=bus,
        api_base=f"http://127.0.0.1:{api_port}",
    )
    qq.start()
    port = qq._server.server_address[1]  # type: ignore[union-attr]

    # 发送 OneBot 事件到 QQ 渠道
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/onebot/event",
        data=json.dumps(
            {
                "post_type": "message",
                "message_type": "private",
                "user_id": 12345,
                "raw_message": "hi from qq",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    assert payload["ok"] is True
    assert payload["queued"] is True

    # 验证入站消息已发布到 MessageBus
    inbound = bus.consume_inbound()
    assert inbound is not None
    assert inbound.session_id == "qq_12345"
    assert inbound.text == "hi from qq"

    # 模拟出站回复：QQ 渠道的 on_outbound 会调用 _send_private_msg
    outbound = OutboundMessage(channel="qq", session_id="qq_12345", text="pong to qq")
    outbound.metadata["qq_user_id"] = 12345
    bus.dispatch_outbound(outbound)

    # 验证 QQ 渠道收到了出站消息并发送到 API
    qq.stop()
    api_server.shutdown()
    api_server.server_close()
    assert pushed
    assert pushed[-1]["user_id"] == 12345
    assert pushed[-1]["message"] == "pong to qq"