import json
import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from flow_agent.dashboard.store import InMemoryDashboardStore


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DashboardServer:
    """Minimal HTTP API for runtime inspection."""

    host: str
    port: int
    store: InMemoryDashboardStore
    _server: HTTPServer | None = None
    _thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        self._server = HTTPServer((self.host, self.port), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("dashboard server started on %s:%s", self.host, self.port)

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
        logger.info("dashboard server stopped")

    def _make_handler(self) -> Callable[..., BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path not in {"/", "/snapshot"}:
                    self.send_response(404)
                    self.end_headers()
                    return
                snap = parent.store.snapshot()
                payload = {
                    "turns": snap.turns,
                    "tools": snap.tools,
                    "proactive": snap.proactive,
                    "jobs": snap.jobs,
                    "subagents": snap.subagents,
                }
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args) -> None:  # noqa: A002
                return

        return Handler

