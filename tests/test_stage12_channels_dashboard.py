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


def test_cli_channel_handles_line():
    def handler(msg: InboundMessage) -> OutboundMessage:
        return OutboundMessage(channel=msg.channel, session_id=msg.session_id, text=f"ok:{msg.text}")

    cli = CLIChannel(handler=handler, default_session_id="s1")
    cli.start()
    assert cli.handle_line("hi") == "ok:hi"
    cli.stop()


def test_http_channel_inbound_roundtrip():
    def handler(msg: InboundMessage) -> OutboundMessage:
        return OutboundMessage(channel=msg.channel, session_id=msg.session_id, text="pong")

    http = HTTPChannel(host="127.0.0.1", port=0, handler=handler)
    http.start()
    # resolve actual port
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
    assert payload["reply"] == "pong"
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


def test_qq_channel_private_message_roundtrip():
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

    def handler(msg: InboundMessage) -> OutboundMessage:
        assert msg.session_id == "qq_12345"
        assert msg.text == "hi from qq"
        return OutboundMessage(channel=msg.channel, session_id=msg.session_id, text="pong to qq")

    qq = QQChannel(
        host="127.0.0.1",
        port=0,
        handler=handler,
        api_base=f"http://127.0.0.1:{api_port}",
    )
    qq.start()
    port = qq._server.server_address[1]  # type: ignore[union-attr]
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
    assert payload["reply_sent"] is True
    qq.stop()
    api_server.shutdown()
    api_server.server_close()
    assert pushed
    assert pushed[-1]["user_id"] == 12345
    assert pushed[-1]["message"] == "pong to qq"

