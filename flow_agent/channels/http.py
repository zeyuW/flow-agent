import json
import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from flow_agent.channels.base import ChannelStatus, InboundHandler
from flow_agent.channels.models import InboundMessage


logger = logging.getLogger(__name__)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    return json.loads(raw.decode("utf-8"))


@dataclass(slots=True)
class HTTPChannel:
    """HTTP webhook channel.

    Endpoints:
    - POST /inbound  body: {"session_id": "...", "text": "..."}
      response: {"ok": true, "reply": "..."}.
    """

    host: str
    port: int
    handler: InboundHandler
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
        self._server = HTTPServer((self.host, self.port), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._running = True
        logger.info("http channel started on %s:%s", self.host, self.port)

    def stop(self) -> None:
        if not self._running:
            return
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        self._server = None
        self._thread = None
        self._running = False
        logger.info("http channel stopped")

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self._running, last_error=self._last_error)

    def _make_handler(self) -> Callable[..., BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                try:
                    if self.path != "/inbound":
                        self.send_response(404)
                        self.end_headers()
                        return
                    data = _read_json(self)
                    session_id = str(data.get("session_id") or "default")
                    text = str(data.get("text") or "")
                    inbound = InboundMessage(channel=parent.name, session_id=session_id, text=text)
                    out = parent.handler(inbound)
                    reply = out.text if out is not None else ""
                    payload = {"ok": True, "reply": reply}
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

            def log_message(self, format: str, *args) -> None:  # noqa: A002
                return

        return Handler

