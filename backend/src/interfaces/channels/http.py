import json
import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from time import perf_counter
from typing import Callable

from interfaces.channels.base import ChannelStatus, MessageBusChannel
from modules.conversation.domain.channel_message import InboundMessage
from modules.delivery.domain.messages import OutboundMessage
from modules.delivery.infra.delivery_bus import DeliveryBus
from infra.security.auth import APIKeyAuth
from infra.security.policy import SecurityPolicy


logger = logging.getLogger(__name__)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    return json.loads(raw.decode("utf-8"))


@dataclass
class HTTPChannel(MessageBusChannel):
    """HTTP webhook 渠道：基于 DeliveryBus。

    Endpoints:
    - POST /inbound  body: {"session_id": "...", "text": "..."}
      response: {"ok": true, "queued": true}

    出站通过 subscribe_outbound 订阅异步处理。
    """

    host: str
    port: int
    message_bus: DeliveryBus
    auth: APIKeyAuth | None = None
    security_policy: SecurityPolicy | None = None
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
        # 通过 subscribe_outbound 注册 _on_response 回调
        self.message_bus.subscribe_outbound(self.name, self._on_response)
        self._server = HTTPServer((self.host, self.port), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._running = True
        logger.info("http channel started on %s:%s (outbound subscriber registered)", self.host, self.port)

    def stop(self) -> None:
        if not self._running:
            return
        # 取消出站订阅
        self.message_bus.unsubscribe_outbound(self.name, self._on_response)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self._server = None
        self._thread = None
        self._running = False
        logger.info("http channel stopped")

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self._running, last_error=self._last_error)

    def _on_response(self, message: OutboundMessage) -> None:
        """收到出站回复时的回调函数。

        由 DeliveryBus 后台 dispatch_outbound 任务调用。
        HTTP 渠道的出站目前通过日志记录，未来可用于异步推送（如 WebSocket）。
        """
        logger.debug("http outbound: channel=%s session=%s text=%s",
                     message.channel, message.session_id, message.text[:100])

    def on_outbound(self, message: OutboundMessage) -> None:
        """收到出站回复（兼容旧接口，转发到 _on_response）。"""
        self._on_response(message)

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

            def log_message(self, format: str, *args) -> None:
                return

        return Handler
