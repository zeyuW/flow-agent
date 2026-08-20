"""追踪页面使用的只读 FastAPI 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, FastAPI, HTTPException, Query

from application.agent.app.tracing import TraceTimeline
from interfaces.admin.schemas import (
    EventSummary,
    TraceDetail,
    TraceStatus,
    TraceSummary,
)


def create_admin_app(timeline: TraceTimeline) -> FastAPI:
    """创建不含写操作的本机管理 API。"""

    app = FastAPI(title="Flow Agent Admin API", docs_url=None, redoc_url=None)
    router = APIRouter(prefix="/api")

    @router.get("/traces", response_model=list[TraceSummary])
    def list_traces(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        status: TraceStatus | None = None,
        channel: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            record.as_summary()
            for record in timeline.list_traces(limit, status, channel)
        ]

    @router.get("/traces/{trace_id}", response_model=TraceDetail)
    def get_trace(trace_id: str) -> dict[str, object]:
        record = timeline.get_trace(trace_id)
        if record is None:
            raise HTTPException(404, detail=f"未找到追踪记录: {trace_id}")
        return record.as_detail()

    @router.get("/events", response_model=list[EventSummary])
    def list_events(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        trace_id: str | None = None,
        type: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {
                "trace_id": event.trace_id,
                "type": event.type,
                "at": event.at,
                "status": event.status,
                "summary": event.summary,
            }
            for event in timeline.list_events(limit, trace_id, type)
        ]

    app.include_router(router)
    return app
