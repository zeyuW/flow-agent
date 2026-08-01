import json
import logging
import threading
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from interfaces.channels.base import ChannelStatus, MessageBusChannel
from modules.conversation.domain.channel_message import InboundMessage
from modules.delivery.domain.messages import OutboundMessage
from flow_agent.messaging.message_bus import MessageBus


logger = logging.getLogger(__name__)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    raw = _read_body(handler) or b"{}"
    return json.loads(raw.decode("utf-8"))


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    transfer_encoding = (handler.headers.get("Transfer-Encoding", "") or "").lower()
    if "chunked" in transfer_encoding:
        return _read_chunked(handler)
    length = int(handler.headers.get("Content-Length", "0") or "0")
    return handler.rfile.read(length) if length > 0 else b""


def _read_chunked(handler: BaseHTTPRequestHandler) -> bytes:
    body = bytearray()
    while True:
        line = handler.rfile.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            size = int(line.split(b";", 1)[0], 16)
        except ValueError:
            break
        if size <= 0:
            handler.rfile.readline()
            break
        chunk = handler.rfile.read(size)
        body.extend(chunk)
        handler.rfile.read(2)
    return bytes(body)


@dataclass
class QQChannel(MessageBusChannel):
    """QQ 渠道：基于 MessageBus 的 OneBot 兼容渠道。

    入站：接收 OneBot HTTP POST → 封装 InboundMessage → publish_inbound
    出站：通过 subscribe_outbound 注册 _on_response 回调
          → MessageBus 后台 dispatch 任务调用回调 → POST send_private_msg
    """

    host: str
    port: int
    message_bus: MessageBus
    api_base: str
    access_token: str = ""
    _server: HTTPServer | None = None
    _thread: threading.Thread | None = None
    _running: bool = False
    _last_error: str | None = None

    @property
    def name(self) -> str:
        return "qq"

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
        logger.info("qq channel webhook started on %s:%s (outbound subscriber registered)", self.host, self.port)

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
        logger.info("qq channel stopped")

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self._running, last_error=self._last_error)

    def _on_response(self, message: OutboundMessage) -> None:
        """收到出站回复时的回调函数。

        由 MessageBus 后台 dispatch_outbound 任务调用。
        负责调用 QQ API 将消息发送给用户。
        """
        qq_user_id = int(message.metadata.get("qq_user_id", 0))
        if qq_user_id <= 0:
            logger.warning("qq outbound: no qq_user_id in metadata, skipping")
            return
        try:
            self._send_private_msg(user_id=qq_user_id, message=message.text)
        except Exception:
            logger.exception("qq outbound send failed")
            raise  # 让 MessageBus 的容错重试机制处理

    def on_outbound(self, message: OutboundMessage) -> None:
        """收到出站回复（兼容旧接口，转发到 _on_response）。"""
        self._on_response(message)

    def _make_handler(self) -> Callable[..., BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                try:
                    if self.path != "/onebot/event":
                        self.send_response(404)
                        self.end_headers()
                        return
                    event = _read_json(self)
                    if str(event.get("post_type") or "") != "message":
                        _ok(self, {"ok": True, "ignored": "non_message_event"})
                        return
                    if str(event.get("message_type") or "") != "private":
                        _ok(self, {"ok": True, "ignored": "non_private_message"})
                        return
                    user_id = int(str(event.get("user_id") or "0"))
                    text = str(event.get("raw_message") or event.get("message") or "").strip()
                    if user_id <= 0 or not text:
                        _ok(self, {"ok": True, "ignored": "invalid_payload"})
                        return
                    inbound = InboundMessage(parent.name, f"qq_{user_id}", text)
                    inbound.metadata["qq_user_id"] = user_id
                    # 通过 MessageBus 发布入站消息
                    parent.message_bus.publish_inbound(inbound)
                    _ok(self, {"ok": True, "queued": True})
                except Exception as exc:
                    parent._last_error = str(exc)
                    logger.exception("qq channel request failed")
                    raw = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

            def log_message(self, format: str, *args) -> None:
                return

        return Handler

    def _send_private_msg(self, user_id: int, message: str) -> None:
        payload = json.dumps({"user_id": user_id, "message": message}, ensure_ascii=False).encode("utf-8")
        url = f"{self.api_base.rstrip('/')}/send_private_msg"
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
            headers["X-Access-Token"] = self.access_token
            url = _with_access_token(url, self.access_token)
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=3) as resp:
            resp.read()


def _with_access_token(url: str, token: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("access_token", token)
    new_query = urlencode(query)
    return urlunparse(parsed._replace(query=new_query))


def _ok(handler: BaseHTTPRequestHandler, payload: dict[str, object]) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)
