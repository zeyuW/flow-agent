import json
import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from time import perf_counter
from typing import Callable

from flow_agent.channels.base import ChannelStatus, MessageBusChannel
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.messaging.message_bus import MessageBus
from flow_agent.ops.metrics import MetricsStore
from flow_agent.security.auth import APIKeyAuth
from flow_agent.security.policy import SecurityPolicy


logger = logging.getLogger(__name__)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    return json.loads(raw.decode("utf-8"))


@dataclass
class HTTPChannel(MessageBusChannel):
    """HTTP webhook 渠道：基于 MessageBus。

    Endpoints:
    - POST /inbound  body: {"session_id": "...", "text": "..."}
      response: {"ok": true, "queued": true}
    """

    host: str
    port: int
    message_bus: MessageBus
    auth: APIKeyAuth | None = None
    security_policy: SecurityPolicy | None = None
    metrics: MetricsStore | None = None
    _server: HTTPServer | None = None
    _thread: threading.Thread | None = None
    _running: bool = False
    _last_error: str | None = None

    @property
    def name(self) -> str:
        return "http"

    def start(self) -> None:
        if self._running:
            return
        self._last_error = None
        self.message_bus.subscribe_outbound(self)
        self._server = HTTPServer((self.host, self.port), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._running = True
        logger.info("http channel started on %s:%s (message bus connected)", self.host, self.port)

    def stop(self) -> None:
        if not self._running:
            return
        self.message_bus.outbound.unsubscribe(self)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self._server = None
        self._thread = None
        self._running = False
        logger.info("http channel stopped")

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self._running, last_error=self._last_error)

    def on_outbound(self, message: OutboundMessage) -> None:
        """HTTP 渠道的出站目前通过 HTTP 响应直接返回。

        对于同步 HTTP 请求，回复在请求处理中直接返回；
        on_outbound 保留用于将来的异步推送场景。
        """
        logger.debug("http outbound: %s", message.text[:100])

    def _make_handler(self) -> Callable[..., BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                started = perf_counter()
                try:
                    if self.path != "/inbound":
                        self.send_response(404)
                        self.end_headers()
                        return
                    source = self.headers.get("X-Source", "") or self.client_address[0]
                    if parent.security_policy is not None:
                        allowed, reason = parent.security_policy.check_channel_source(source)
                        if not allowed:
                            payload = {"ok": False, "error": reason}
                            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                            self.send_response(403)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            self.send_header("Content-Length", str(len(raw)))
                            self.end_headers()
                            self.wfile.write(raw)
                            return
                    if parent.auth is not None:
                        provided = self.headers.get("X-API-Key")
                        if not parent.auth.verify(provided):
                            payload = {"ok": False, "error": "unauthorized"}
                            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                            self.send_response(401)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            self.send_header("Content-Length", str(len(raw)))
                            self.end_headers()
                            self.wfile.write(raw)
                            return
                    data = _read_json(self)
                    session_id = str(data.get("session_id") or "default")
                    text = str(data.get("text") or "")
                    inbound = InboundMessage(channel=parent.name, session_id=session_id, text=text)
                    parent.message_bus.publish_inbound(inbound)
                    payload = {"ok": True, "queued": True}
                    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    if parent.metrics is not None:
                        parent.metrics.inc("channel.http.request_ok")
                except Exception as exc:
                    parent._last_error = str(exc)
                    logger.exception("http channel request failed")
                    payload = {"ok": False, "error": str(exc)}
                    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    if parent.metrics is not None:
                        parent.metrics.inc("channel.http.request_failed")
                finally:
                    if parent.metrics is not None:
                        elapsed_ms = round((perf_counter() - started) * 1000)
                        parent.metrics.inc(f"channel.http.latency_bucket_ms_{min(1000, elapsed_ms // 100 * 100)}")

            def log_message(self, format: str, *args) -> None:
                return

        return Handler