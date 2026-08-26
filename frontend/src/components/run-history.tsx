"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { getLogs } from "@/lib/api/client";
import type { LogPage } from "@/lib/api/schemas";

type Stage = "passive" | "proactive" | "memory" | "subagent" | "tool";
type Level = "INFO" | "WARN" | "ERROR";

const stageLabels: Record<Stage, string> = { passive: "对话", proactive: "主动链路", memory: "记忆", subagent: "子 Agent", tool: "工具" };

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
}

function rangeStart(range: string) {
  if (range === "all") return undefined;
  const now = new Date();
  if (range === "today") now.setHours(0, 0, 0, 0);
  else now.setMinutes(now.getMinutes() - (range === "quarter" ? 15 : 60));
  return now.toISOString();
}

function eventIcon(stage: Stage) {
  return stage === "proactive" ? "↗" : stage === "memory" ? "◌" : stage === "subagent" ? "◇" : stage === "tool" ? "⚙" : "→";
}

function selectedLog(data: LogPage | undefined, id: string | undefined) {
  return data?.items.find((item) => item.trace_id === id) ?? data?.items[0];
}

export function RunHistory() {
  const [stage, setStage] = useState<Stage | "all">("all");
  const [level, setLevel] = useState<Level | "all">("all");
  const [timeRange, setTimeRange] = useState("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string>();
  const [copiedTrace, setCopiedTrace] = useState(false);
  const pageSize = 5;
  const logsQuery = useQuery({
    queryKey: ["logs", page, stage, level, query, timeRange],
    queryFn: () => getLogs({ limit: pageSize, offset: (page - 1) * pageSize, stage: stage === "all" ? undefined : stage, level: level === "all" ? undefined : level, q: query.trim() || undefined, start_at: rangeStart(timeRange) })
  });
  const data = logsQuery.data;
  const selected = selectedLog(data, selectedId);
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));

  async function copyTrace(trace: string) {
    await navigator.clipboard?.writeText(trace);
    setCopiedTrace(true);
    window.setTimeout(() => setCopiedTrace(false), 1500);
  }

  function reset() {
    setStage("all"); setLevel("all"); setTimeRange("all"); setQuery(""); setPage(1); setSelectedId(undefined);
  }

  return (
    <div className="run-history-page">
      <div className="log-breadcrumb" aria-label="面包屑导航"><span>控制台</span><span>/</span><strong>日志</strong></div>
      <form aria-label="运行记录筛选" className="run-filters" onSubmit={(event) => { event.preventDefault(); setPage(1); }}>
        <label className="run-search"><span>搜索</span><input aria-label="搜索运行记录" onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="Trace ID、错误或事件名称" value={query} /></label>
        <button className="search-action" type="submit">搜索</button>
        <label><span>业务阶段</span><select aria-label="业务阶段" onChange={(event) => { setStage(event.target.value as Stage | "all"); setPage(1); }} value={stage}><option value="all">全部阶段</option>{Object.entries(stageLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label><span>日志级别</span><select aria-label="日志级别" onChange={(event) => { setLevel(event.target.value as Level | "all"); setPage(1); }} value={level}><option value="all">全部级别</option><option value="INFO">INFO</option><option value="WARN">WARN</option><option value="ERROR">ERROR</option></select></label>
        <label><span>时间范围</span><select aria-label="时间范围" onChange={(event) => { setTimeRange(event.target.value); setPage(1); }} value={timeRange}><option value="all">全部时间</option><option value="quarter">最近 15 分钟</option><option value="hour">最近 1 小时</option><option value="today">今天</option></select></label>
        <button className="filter-action" onClick={reset} type="button">重置</button>
      </form>
      <div className="filter-status-row"><div className="active-filters"><span>当前筛选</span><span>{stage === "all" && level === "all" && timeRange === "all" ? "全部日志" : `${stageLabels[stage as Stage] ?? "全部阶段"} · ${level} · ${timeRange}`}</span></div><button className="refresh-action" onClick={() => void logsQuery.refetch()} type="button">刷新</button></div>
      <section className="run-workspace">
        <div className="run-list-panel">
          <div className="run-list-header"><strong>事件时间线</strong><span>{data?.total ?? 0} 条记录</span></div>
          <div className="run-list">
            {logsQuery.isPending ? <p className="empty-state">正在读取日志…</p> : logsQuery.isError ? <p className="empty-state">无法读取日志，请检查管理 API。</p> : data?.items.length === 0 ? <p className="empty-state">没有符合条件的日志。</p> : data?.items.map((event) => { const itemStage = (event.stage in stageLabels ? event.stage : "passive") as Stage; const lastEvent = event.events[event.events.length - 1]; return <button className={`run-event ${event.trace_id === selected?.trace_id ? "run-event-selected" : ""}`} key={event.trace_id} onClick={() => setSelectedId(event.trace_id)} type="button"><span className={`event-icon event-icon-${itemStage}`} aria-hidden="true">{eventIcon(itemStage)}</span><span className="run-event-main"><span className="run-event-title"><time>{formatTime(event.started_at ?? "")}</time><strong>{lastEvent?.title ?? "Agent 请求"}</strong><span className={`level-label level-text-${event.level.toLowerCase()}`}>{event.level}</span></span><span className="run-event-detail">{event.event_count} 个事件 · {event.duration_ms}ms · {event.status}</span><span className="run-event-meta"><span className={`stage-tag stage-${itemStage}`}>{stageLabels[itemStage]}</span><code>{event.trace_id}</code><span>{event.session_id ?? "—"}</span></span></span></button>; })}
          </div>
          <footer className="run-list-footer"><span>共 {data?.total ?? 0} 条</span><span className="pagination"><button disabled={page <= 1} onClick={() => setPage((current) => current - 1)} type="button">上一页</button><strong>{page} / {pageCount}</strong><button disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)} type="button">下一页</button></span></footer>
        </div>
        <aside aria-label="运行记录详情" className="run-detail-panel">
          {selected ? <><div className="run-detail-header"><div><span className={`level-label level-text-${selected.level.toLowerCase()}`}>{selected.level}</span><h2>{selected.events[selected.events.length - 1]?.title ?? "Agent 请求"}</h2></div><div className="detail-actions"><span className={`stage-tag stage-${selected.stage}`}>{stageLabels[selected.stage as Stage] ?? selected.stage}</span><button onClick={() => void copyTrace(selected.trace_id)} type="button">{copiedTrace ? "已复制" : "复制 Trace"}</button></div></div><dl className="run-detail-facts"><div><dt>Trace ID</dt><dd><code>{selected.trace_id}</code></dd></div><div><dt>开始时间</dt><dd>{formatTime(selected.started_at ?? "")}</dd></div><div><dt>耗时</dt><dd>{selected.duration_ms}ms</dd></div><div><dt>当前状态</dt><dd className={selected.level === "ERROR" ? "status-error" : "status-ok"}>{selected.status}</dd></div><div><dt>会话 ID</dt><dd><code>{selected.session_id ?? "—"}</code></dd></div></dl><div className="run-detail-block"><span className="detail-label">事件链 · {selected.event_count} 个事件</span>{selected.events.map((event) => <p key={`${event.type}-${event.at}`}><strong>{formatTime(event.at)} · {event.title}</strong><br />{event.detail}</p>)}</div><details className="raw-log-details"><summary>查看结构化数据</summary><pre>{JSON.stringify(selected, null, 2)}</pre></details></> : <p className="empty-state">选择一条记录查看详情。</p>}
        </aside>
      </section>
    </div>
  );
}
