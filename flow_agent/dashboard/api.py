import json
import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

from flow_agent.dashboard.store import InMemoryDashboardStore


logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dashboard"


@dataclass(slots=True)
class DashboardServer:
    """Minimal HTTP API for runtime inspection."""

    host: str
    port: int
    store: InMemoryDashboardStore
    runtime_snapshot_provider: Callable[[], dict[str, Any]] | None = None
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
                if self.path in {"/ui", "/ui/"}:
                    self._send_frontend_file("index.html", "text/html; charset=utf-8")
                    return
                if self.path.startswith("/ui/"):
                    asset = self.path.removeprefix("/ui/")
                    if asset == "index.html":
                        self._send_frontend_file("index.html", "text/html; charset=utf-8")
                    elif asset == "style.css":
                        self._send_frontend_file("style.css", "text/css; charset=utf-8")
                    elif asset == "app.js":
                        self._send_frontend_file("app.js", "application/javascript; charset=utf-8")
                    else:
                        self.send_response(404)
                        self.end_headers()
                    return
                if self.path not in {"/", "/snapshot", "/runtime", "/runtime/quality"}:
                    self.send_response(404)
                    self.end_headers()
                    return
                if self.path == "/runtime":
                    payload = (
                        parent.runtime_snapshot_provider()
                        if parent.runtime_snapshot_provider is not None
                        else {}
                    )
                elif self.path == "/runtime/quality":
                    runtime_payload = (
                        parent.runtime_snapshot_provider()
                        if parent.runtime_snapshot_provider is not None
                        else {}
                    )
                    payload = (
                        runtime_payload.get("event_summary", {}).get("quality", {})
                        if isinstance(runtime_payload, dict)
                        else {}
                    )
                else:
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

            def _send_frontend_file(self, name: str, content_type: str) -> None:
                file_path = FRONTEND_DIR / name
                if not file_path.exists():
                    self.send_response(404)
                    self.end_headers()
                    return
                raw = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args) -> None:  # noqa: A002
                return

        return Handler

