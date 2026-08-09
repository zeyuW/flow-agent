"""通用 HTTP Webhook 渠道适配器。

该渠道主要用于本地或外部系统把统一 JSON 消息接入 Flow Agent，本身不负责
实现具体 IM 平台协议。
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from time import perf_counter
from typing import Callable

from infra.bus.types import ChannelDeliveryResult, OutboundMessage
from infra.security import APIKeyAuth, SecurityPolicy
from interfaces.channels.base import BaseChannelAdapter, ChannelCapabilities


logger = logging.getLogger(__name__)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    return json.loads(raw.decode("utf-8"))


class HTTPChannel(BaseChannelAdapter):
    """接收 `POST /inbound` 的通用 HTTP 渠道。"""

    capabilities = ChannelCapabilities(text=False)

    def __init__(
        self,
        host: str,
        port: int,
        auth: APIKeyAuth | None = None,
        security_policy: SecurityPolicy | None = None,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.auth = auth
        self.security_policy = security_policy
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return "http"

    def _start_platform(self) -> None:
        self._server = HTTPServer((self.host, self.port), self._make_handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="http-channel",
            daemon=True,
        )
        self._thread.start()
        logger.info("HTTP 渠道启动: %s:%s", self.host, self.port)

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
        del recipient_id, text
        return ChannelDeliveryResult(
            delivered=False,
            retryable=False,
            error="HTTP 渠道不支持主动文本投递",
        )

    def _deliver_outbound(self, message: OutboundMessage) -> ChannelDeliveryResult:
        logger.debug(
            "HTTP 出站消息: channel=%s session=%s text=%s",
            message.channel,
            message.session_id,
            message.text[:100],
        )
        return ChannelDeliveryResult(
            delivered=False,
            retryable=False,
            error="HTTP 渠道不支持主动出站投递",
        )

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
                            self._write_json(403, {"ok": False, "error": reason})
                            return
                    if parent.auth is not None and not parent.auth.verify(
                        self.headers.get("X-API-Key")
                    ):
                        self._write_json(401, {"ok": False, "error": "unauthorized"})
                        return

                    data = _read_json(self)
                    session_id = str(data.get("session_id") or data.get("chat_id") or "default")
                    chat_id = str(data.get("chat_id") or session_id)
                    sender_id = str(data.get("sender_id") or "http")
                    text = str(data.get("text") or "")
                    parent.publish_inbound(
                        session_id=session_id,
                        chat_id=chat_id,
                        sender_id=sender_id,
                        text=text,
                        metadata={"source": source, "elapsed_ms": int((perf_counter() - started) * 1000)},
                    )
                    self._write_json(200, {"ok": True, "queued": True})
                except Exception as exc:
                    parent._last_error = str(exc)
                    logger.exception("HTTP 渠道请求失败")
                    self._write_json(500, {"ok": False, "error": str(exc)})

            def _write_json(self, status: int, payload: dict[str, object]) -> None:
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args) -> None:
                del format, args
                return

        return Handler
