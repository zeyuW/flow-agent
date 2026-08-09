"""基于 OneBot HTTP 协议的 QQ 渠道适配器。"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from infra.bus.types import ChannelDeliveryResult, OutboundMessage
from interfaces.channels.base import BaseChannelAdapter, ChannelCapabilities


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
        body.extend(handler.rfile.read(size))
        handler.rfile.read(2)
    return bytes(body)


class QQChannel(BaseChannelAdapter):
    """接收 OneBot 私聊事件并发送私聊文本。"""

    capabilities = ChannelCapabilities(text=True)

    def __init__(
        self,
        host: str,
        port: int,
        api_base: str,
        access_token: str = "",
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.api_base = api_base
        self.access_token = access_token
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return "qq"

    def _start_platform(self) -> None:
        self._server = HTTPServer((self.host, self.port), self._make_handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="qq-channel",
            daemon=True,
        )
        self._thread.start()
        logger.info("OneBot QQ 渠道启动: %s:%s", self.host, self.port)

    def _stop_platform(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self._server = None

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    def send_text(self, *, recipient_id: str, text: str) -> ChannelDeliveryResult:
        self._send_private_msg(int(recipient_id), text)
        return ChannelDeliveryResult(delivered=True)

    def _deliver_outbound(self, message: OutboundMessage) -> ChannelDeliveryResult:
        target = message.chat_id or message.session_id
        if not target:
            return ChannelDeliveryResult(
                delivered=False,
                retryable=False,
                error="QQ 出站消息缺少 chat_id",
            )
        self._send_private_msg(int(target), message.text)
        return ChannelDeliveryResult(delivered=True)

    def _make_handler(self) -> Callable[..., BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                try:
                    if self.path != "/onebot/event":
                        _ok(self, {"ok": False, "error": "not_found"}, status=404)
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
                    parent.publish_inbound(
                        session_id=f"qq:{user_id}",
                        chat_id=str(user_id),
                        sender_id=str(user_id),
                        text=text,
                        metadata={"provider_user_id": user_id},
                    )
                    _ok(self, {"ok": True, "queued": True})
                except Exception as exc:
                    parent._last_error = str(exc)
                    logger.exception("OneBot QQ 请求失败")
                    _ok(self, {"ok": False, "error": str(exc)}, status=500)

            def log_message(self, format: str, *args) -> None:
                del format, args
                return

        return Handler

    def _send_private_msg(self, user_id: int, message: str) -> None:
        payload = json.dumps(
            {"user_id": user_id, "message": message}, ensure_ascii=False
        ).encode("utf-8")
        url = f"{self.api_base.rstrip('/')}/send_private_msg"
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
            headers["X-Access-Token"] = self.access_token
            url = _with_access_token(url, self.access_token)
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=3) as response:
            response.read()


def _with_access_token(url: str, token: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("access_token", token)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _ok(
    handler: BaseHTTPRequestHandler,
    payload: dict[str, object],
    *,
    status: int = 200,
) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)
