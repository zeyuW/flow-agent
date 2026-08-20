"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { EventTimeline } from "@/components/event-timeline";
import { StatusBadge } from "@/components/status-badge";
import { ThemeToggle } from "@/components/theme-toggle";
import { TraceDetailPanel } from "@/components/trace-detail";
import { WorkbenchShell } from "@/components/workbench-shell";
import { getEvents, getTrace, getTraces } from "@/lib/api/client";
import type { RuntimeStatus, TraceSummary } from "@/lib/api/schemas";

function badgeStatus(status: string): RuntimeStatus {
  if (status === "failed" || status === "error") return "failed";
  if (status === "completed" || status === "ok") return "healthy";
  if (status === "running" || status === "started") return "degraded";
  return "unknown";
}

function TraceRow({ trace, selected, onSelect }: { trace: TraceSummary; selected: boolean; onSelect: () => void }) {
  return (
    <button className={`trace-row${selected ? " trace-row-selected" : ""}`} onClick={onSelect} type="button">
      <span>
        <strong>{trace.channel}</strong>
        <small>{trace.id}</small>
      </span>
      <span>
        <StatusBadge status={badgeStatus(trace.status)} />
        <small>{trace.duration_ms} ms</small>
      </span>
    </button>
  );
}

export default function OverviewPage() {
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const tracesQuery = useQuery({ queryKey: ["traces"], queryFn: getTraces, refetchInterval: 30_000 });
  const eventsQuery = useQuery({ queryKey: ["events"], queryFn: getEvents, refetchInterval: 30_000 });
  const activeTraceId = selectedTraceId ?? tracesQuery.data?.[0]?.id ?? null;
  const traceQuery = useQuery({
    queryKey: ["trace", activeTraceId],
    queryFn: () => getTrace(activeTraceId ?? ""),
    enabled: activeTraceId !== null
  });
  const latestUpdate = Math.max(tracesQuery.dataUpdatedAt, eventsQuery.dataUpdatedAt);

  return (
    <WorkbenchShell
      details={<TraceDetailPanel trace={traceQuery.data} />}
      header={<><div className="global-status"><span>Trace 数</span><strong>{tracesQuery.data?.length ?? "—"}</strong></div><div className="global-status hide-on-narrow"><span>近期事件</span><strong>{eventsQuery.data?.length ?? "—"}</strong></div><ThemeToggle /></>}
    >
      <section className="page-heading"><div><p className="eyebrow">Trace 调查</p><h1>运行追踪</h1><p className="muted">来自 flow-agent-admin-api 的只读处理轨迹，每 30 秒刷新一次。</p></div><p className="muted">{latestUpdate ? `上次刷新：${new Date(latestUpdate).toLocaleTimeString("zh-CN")}` : "正在建立首次快照…"}</p></section>
      {tracesQuery.isError ? <section className="empty-state" role="alert">无法读取 Trace 列表。请确认管理 API 地址与代理配置。</section> : <section className="panel"><div className="section-title"><div><p className="eyebrow">处理记录</p><h2>最近 Trace</h2></div>{tracesQuery.isFetching && <span className="muted">刷新中…</span>}</div><div className="trace-list">{tracesQuery.data?.map((trace) => <TraceRow key={trace.id} trace={trace} selected={trace.id === activeTraceId} onSelect={() => setSelectedTraceId(trace.id)} />) ?? <p className="empty-state">正在读取 Trace…</p>}</div></section>}
      <section className="panel events-panel"><div className="section-title"><div><p className="eyebrow">运行事件</p><h2>近期事件</h2></div></div>{eventsQuery.isError ? <p className="empty-state" role="alert">无法读取近期事件。</p> : <EventTimeline events={eventsQuery.data ?? []} onSelectTrace={setSelectedTraceId} />}</section>
      <section className="panel mobile-trace-detail"><TraceDetailPanel trace={traceQuery.data} /></section>
    </WorkbenchShell>
  );
}
