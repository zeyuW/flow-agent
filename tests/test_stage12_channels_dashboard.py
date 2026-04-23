import json
import urllib.request
from pathlib import Path

from flow_agent.channels.cli import CLIChannel
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.channels.http import HTTPChannel
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

