"""追踪页面使用的只读 FastAPI 路由。"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, HTTPException, Query

from application.agent.app.tracing import TraceTimeline
from application.capabilities.app.capability_query import CapabilityQueryService
from application.capabilities.skills.installer import SkillInstaller
from application.capabilities.mcp.server_registry import McpServerRegistry
from application.passive.app.session_query import SessionQueryService
from application.schedule.app.runtime import SchedulerService
from interfaces.admin.schemas import (
    CreateSchedule,
    CapabilitySnapshot,
    EventSummary,
    InstallSkill,
    SkillListResponse,
    SkillRepository,
    McpServerEnabled,
    McpServerInput,
    SessionDetail,
    SessionSummary,
    ScheduleSummary,
    TraceDetail,
    TraceStatus,
    TraceSummary,
)


def create_admin_app(
    timeline: TraceTimeline,
    session_query: SessionQueryService,
    scheduler: SchedulerService,
    capability_query: CapabilityQueryService | None = None,
    skill_installer: SkillInstaller | None = None,
    mcp_registry: McpServerRegistry | None = None,
) -> FastAPI:
    """创建本机管理 API。"""

    app = FastAPI(title="Flow Agent Admin API", docs_url=None, redoc_url=None)
    router = APIRouter(prefix="/api")

    @router.get("/capabilities", response_model=CapabilitySnapshot)
    def get_capabilities() -> dict[str, list[dict[str, Any]]]:
        if capability_query is None:
            return {"skills": [], "connectors": []}
        return capability_query.get_capabilities()

    @router.get("/mcp/servers")
    def list_mcp_servers() -> list[dict[str, Any]]:
        if mcp_registry is None:
            raise HTTPException(503, detail="MCP 管理服务未初始化")
        return mcp_registry.list_configured_servers()

    @router.put("/mcp/servers/{name}")
    def save_mcp_server(name: str, payload: McpServerInput) -> dict[str, Any]:
        if mcp_registry is None:
            raise HTTPException(503, detail="MCP 管理服务未初始化")
        try:
            mcp_registry.upsert_server(name, payload.model_dump())
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        return {
            "name": name,
            "enabled": payload.enabled,
            "connected": False,
            "tools": [],
        }

    @router.delete("/mcp/servers/{name}")
    def delete_mcp_server(name: str) -> dict[str, bool]:
        if mcp_registry is None:
            raise HTTPException(503, detail="MCP 管理服务未初始化")
        if not mcp_registry.remove_server(name):
            raise HTTPException(404, detail=f"未找到 MCP 服务: {name}")
        return {"removed": True}

    @router.post("/mcp/servers/{name}/enabled")
    def set_mcp_enabled(name: str, payload: McpServerEnabled) -> dict[str, bool]:
        if mcp_registry is None:
            raise HTTPException(503, detail="MCP 管理服务未初始化")
        try:
            if not mcp_registry.set_server_enabled(name, payload.enabled):
                raise HTTPException(404, detail=f"未找到 MCP 服务: {name}")
        except HTTPException:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        return {"enabled": payload.enabled}

    @router.post("/skills/scan", response_model=SkillListResponse)
    def scan_skills(payload: SkillRepository) -> dict[str, list[dict[str, str]]]:
        if skill_installer is None:
            raise HTTPException(503, detail="Skill 安装服务未初始化")
        try:
            skills = skill_installer.scan(payload.repository_url)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        return {"skills": [{"name": skill.name} for skill in skills]}

    @router.post("/skills/install", response_model=SkillListResponse)
    def install_skill(payload: InstallSkill) -> dict[str, list[dict[str, str]]]:
        if skill_installer is None:
            raise HTTPException(503, detail="Skill 安装服务未初始化")
        try:
            skills = skill_installer.install(payload.repository_url, payload.names)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        return {"skills": [{"name": skill.name} for skill in skills]}

    @router.delete("/skills/{name}")
    def uninstall_skill(name: str) -> dict[str, bool]:
        if skill_installer is None:
            raise HTTPException(503, detail="Skill 安装服务未初始化")
        try:
            skill_installer.uninstall(name)
        except ValueError as exc:
            raise HTTPException(404, detail=str(exc)) from exc
        return {"removed": True}

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

    @router.get("/sessions", response_model=list[SessionSummary])
    def list_sessions(
        start_date: date,
        end_date: date,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        if start_date > end_date:
            raise HTTPException(422, detail="开始日期不能晚于结束日期")
        return session_query.list_sessions(start_date, end_date, limit)

    @router.get("/sessions/{session_id}", response_model=SessionDetail)
    def get_session(
        session_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        if (start_date is None) != (end_date is None):
            raise HTTPException(422, detail="开始日期和结束日期必须同时提供")
        session = session_query.get_session(
            session_id, start_date=start_date, end_date=end_date
        )
        if session is None:
            raise HTTPException(404, detail=f"未找到会话: {session_id}")
        return session

    @router.get("/schedules", response_model=list[ScheduleSummary])
    def list_schedules():
        return scheduler.list_all_tasks()

    @router.post("/schedules", response_model=ScheduleSummary)
    def create_schedule(payload: CreateSchedule):
        target = scheduler.get_task_by_id(payload.target_task_id)
        if target is None:
            raise HTTPException(404, detail="未找到投递目标")
        try:
            return scheduler.create_task(
                trigger=payload.trigger,
                when=payload.when,
                task_type=payload.task_type,
                message=payload.message,
                name=payload.name,
                channel=target.channel,
                session_id=target.session_id,
                chat_id=target.chat_id,
                timezone_name=target.timezone,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    @router.post("/schedules/{task_id}/cancel")
    def cancel_schedule(task_id: str) -> dict[str, bool]:
        if not scheduler.cancel_task_by_id(task_id):
            raise HTTPException(404, detail=f"未找到定时任务: {task_id}")
        return {"cancelled": True}

    @router.post("/schedules/{task_id}/resume")
    def resume_schedule(task_id: str) -> dict[str, bool]:
        if not scheduler.resume_task_by_id(task_id):
            raise HTTPException(404, detail=f"未找到可恢复的周期任务: {task_id}")
        return {"resumed": True}

    app.include_router(router)
    return app
