"use client";

import { useMemo, useState } from "react";

type Stage = "passive" | "proactive" | "memory" | "subagent";
type Level = "INFO" | "WARN" | "ERROR";

type RunEvent = {
  id: string;
  time: string;
  level: Level;
  stage: Stage;
  title: string;
  detail: string;
  trace: string;
  sessionId: string;
  userId: string;
  inputSummary: string;
  outputSummary: string;
  rawLog: string;
  duration?: string;
};

const events: RunEvent[] = [
  {
    id: "event-1",
    time: "03:28:08.579",
    level: "INFO",
    stage: "proactive",
    title: "主动消息去重命中",
    detail: "候选消息已存在，跳过本次投递。key=1dbfc01dd536ebd0",
    trace: "e2b0363352c6",
    sessionId: "telegram:8706327858",
    userId: "8706327858",
    inputSummary: "候选内容 3 条，用户主题 2 个",
    outputSummary: "decision=skip，未发送消息",
    rawLog: "2026-08-25 03:28:08,579 [INFO] application.proactive.app.resolve: 主动消息去重命中: key=1dbfc01dd536ebd0",
    duration: "4.2s"
  },
  {
    id: "event-2",
    time: "03:28:07.670",
    level: "INFO",
    stage: "proactive",
    title: "LLM request",
    detail: "qwen-turbo · 第 3 次 Judge 推理",
    trace: "e2b0363352c6",
    sessionId: "telegram:8706327858",
    userId: "8706327858",
    inputSummary: "消息 6 条，工具 6 个，约 1.8k tokens",
    outputSummary: "tool_calls=1，输出文本 0 字符",
    rawLog: "2026-08-25 03:28:07,670 [INFO] application.capabilities.llm.client: LLM request stage=proactive model=qwen-turbo",
    duration: "899ms"
  },
  {
    id: "event-3",
    time: "03:27:33.619",
    level: "INFO",
    stage: "memory",
    title: "画像归档模型调用完成",
    detail: "deepseek-v4-flash · 处理待归档事实",
    trace: "memory-919f09ebaa19",
    sessionId: "memory:background",
    userId: "8706327858",
    inputSummary: "待归档事实 4 条，约 620 tokens",
    outputSummary: "画像更新 1 次，输出 486 tokens",
    rawLog: "2026-08-25 03:27:33,619 [INFO] application.capabilities.llm.client: HTTP 200 OK model=deepseek-v4-flash",
    duration: "569ms"
  },
  {
    id: "event-4",
    time: "03:26:41.208",
    level: "ERROR",
    stage: "subagent",
    title: "子 Agent 执行失败",
    detail: "LLM API returned an error · status_code=400",
    trace: "subagent-73ae0f1d",
    sessionId: "telegram:8706327858",
    userId: "8706327858",
    inputSummary: "消息 8 条，工具 4 个，约 3.1k tokens",
    outputSummary: "请求失败，未生成输出",
    rawLog: "2026-08-25 03:26:41,208 [ERROR] application.capabilities.llm.client: LLM API returned an error: Messages with role 'tool' must be a response to a preceding message with 'tool_calls'",
    duration: "1.8s"
  },
  {
    id: "event-5",
    time: "03:25:12.044",
    level: "INFO",
    stage: "passive",
    title: "回合完成",
    detail: "主 Agent 完成 2 次工具调用并发送回复",
    trace: "a4c120fe88d1",
    sessionId: "telegram:8706327858",
    userId: "8706327858",
    inputSummary: "用户消息 1 条，历史消息 12 条",
    outputSummary: "工具调用 2 次，输出文本 184 字符",
    rawLog: "2026-08-25 03:25:12,044 [INFO] application.passive.app.pipeline: turn end session=telegram:8706327858",
    duration: "8.6s"
  },
  {
    id: "event-6",
    time: "03:24:55.103",
    level: "WARN",
    stage: "memory",
    title: "近期上下文压缩失败",
    detail: "已回退到规则摘要，未影响本轮回复",
    trace: "memory-3c11bf52",
    sessionId: "memory:background",
    userId: "8706327858",
    inputSummary: "近期对话 8 条，约 1.2k tokens",
    outputSummary: "模型失败，使用规则摘要",
    rawLog: "2026-08-25 03:24:55,103 [WARNING] application.memory.app.maintenance: 近期上下文模型压缩失败，改用规则摘要",
    duration: "320ms"
  }
];

const stageLabels: Record<Stage, string> = {
  passive: "对话",
  proactive: "主动链路",
  memory: "记忆",
  subagent: "子 Agent"
};

const levelLabels: Record<Level, string> = {
  INFO: "INFO",
  WARN: "WARN",
  ERROR: "ERROR"
};

export function RunHistory() {
  const [stage, setStage] = useState<Stage | "all">("all");
  const [level, setLevel] = useState<Level | "all">("all");
  const [timeRange, setTimeRange] = useState("all");
  const [selectedId, setSelectedId] = useState(events[0].id);
  const [query, setQuery] = useState("");
  const [lastRefreshed, setLastRefreshed] = useState("刚刚");
  const [copiedTrace, setCopiedTrace] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const filteredEvents = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return events.filter((event) => {
      const matchesStage = stage === "all" || event.stage === stage;
      const matchesLevel = level === "all" || event.level === level;
      const matchesTime = timeRange === "all" ||
        timeRange === "today" ||
        (timeRange === "hour" && event.time >= "02:28") ||
        (timeRange === "quarter" && event.time >= "03:25");
      const matchesQuery = !normalizedQuery ||
        `${event.title} ${event.detail} ${event.trace}`.toLowerCase().includes(normalizedQuery);
      return matchesStage && matchesLevel && matchesTime && matchesQuery;
    });
  }, [level, query, stage, timeRange]);

  const selectedEvent = filteredEvents.find((event) => event.id === selectedId) ?? filteredEvents[0];
  const pageSize = 5;
  const pageCount = Math.max(1, Math.ceil(filteredEvents.length / pageSize));
  const visibleEvents = filteredEvents.slice((page - 1) * pageSize, page * pageSize);

  function submitSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
  }

  async function copyTrace(trace: string) {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(trace);
    }
    setCopiedTrace(trace);
    window.setTimeout(() => setCopiedTrace(null), 1500);
  }

  return (
    <div className="run-history-page">
      <div className="log-breadcrumb" aria-label="面包屑导航"><span>控制台</span><span>/</span><strong>日志</strong></div>
      <form aria-label="运行记录筛选" className="run-filters" onSubmit={submitSearch}>
        <label className="run-search">
          <span>搜索</span>
          <input
            aria-label="搜索运行记录"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="trace_id、错误或模型名称"
            value={query}
          />
        </label>
        <button className="search-action" type="submit">搜索</button>
        <label>
          <span>业务阶段</span>
          <select aria-label="业务阶段" onChange={(event) => setStage(event.target.value as Stage | "all")} value={stage}>
            <option value="all">全部阶段</option>
            <option value="passive">对话</option>
            <option value="proactive">主动链路</option>
            <option value="memory">记忆</option>
            <option value="subagent">子 Agent</option>
          </select>
        </label>
        <label>
          <span>日志级别</span>
          <select aria-label="日志级别" onChange={(event) => setLevel(event.target.value as Level | "all")} value={level}>
            <option value="all">全部级别</option>
            <option value="INFO">INFO</option>
            <option value="WARN">WARN</option>
            <option value="ERROR">ERROR</option>
          </select>
        </label>
        <label>
          <span>时间范围</span>
          <select aria-label="时间范围" onChange={(event) => setTimeRange(event.target.value)} value={timeRange}>
            <option value="all">全部时间</option>
            <option value="quarter">最近 15 分钟</option>
            <option value="hour">最近 1 小时</option>
            <option value="today">今天</option>
          </select>
        </label>
        <button className="filter-action" type="button" onClick={() => { setStage("all"); setLevel("all"); setTimeRange("all"); setQuery(""); setPage(1); }}>
          重置
        </button>
      </form>
      <div className="filter-status-row">
        <div className="active-filters">
          <span>当前筛选</span>
          {stage !== "all" ? <button type="button" onClick={() => setStage("all")}>{stageLabels[stage]} ×</button> : null}
          {level !== "all" ? <button type="button" onClick={() => setLevel("all")}>{level} ×</button> : null}
          {timeRange !== "all" ? <button type="button" onClick={() => setTimeRange("all")}>{timeRange === "quarter" ? "最近 15 分钟" : timeRange === "hour" ? "最近 1 小时" : "今天"} ×</button> : null}
          {stage === "all" && level === "all" && timeRange === "all" ? <span>全部日志</span> : null}
        </div>
        <button className="refresh-action" type="button" onClick={() => setLastRefreshed("刚刚")}>刷新 <small>· {lastRefreshed}</small></button>
      </div>

      <section className="run-workspace">
        <div className="run-list-panel">
          <div className="run-list-header">
            <strong>事件时间线</strong>
            <span>{filteredEvents.length} 条记录</span>
          </div>
          <div className="run-list">
            {filteredEvents.length === 0 ? (
              <p className="empty-state">没有符合条件的运行记录。</p>
            ) : visibleEvents.map((event) => (
              <button
                className={`run-event ${event.id === selectedEvent?.id ? "run-event-selected" : ""}`}
                key={event.id}
                onClick={() => setSelectedId(event.id)}
                type="button"
              >
                <span className={`event-icon event-icon-${event.stage}`} aria-hidden="true">{event.stage === "proactive" ? "↗" : event.stage === "memory" ? "◌" : event.stage === "subagent" ? "◇" : "→"}</span>
                <span className="run-event-main">
                  <span className="run-event-title"><time>{event.time}</time><strong>{event.title}</strong><span className={`level-label level-text-${event.level.toLowerCase()}`}>{event.level}</span></span>
                  <span className="run-event-detail">{event.detail}</span>
                  <span className="run-event-meta"><span className={`stage-tag stage-${event.stage}`}>{stageLabels[event.stage]}</span><code>{event.trace}</code><span>{event.sessionId}</span></span>
                </span>
              </button>
            ))}
          </div>
          <footer className="run-list-footer">
            <span>共 {filteredEvents.length} 条</span>
            <span className="pagination"><button disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} type="button">上一页</button><strong>{page} / {pageCount}</strong><button disabled={page >= pageCount} onClick={() => setPage((current) => Math.min(pageCount, current + 1))} type="button">下一页</button></span>
          </footer>
        </div>

        <aside aria-label="运行记录详情" className="run-detail-panel">
          {selectedEvent ? (
            <>
              <div className="run-detail-header">
                <div>
                  <span className={`level-label level-text-${selectedEvent.level.toLowerCase()}`}>{levelLabels[selectedEvent.level]}</span>
                  <h2>{selectedEvent.title}</h2>
                </div>
                <div className="detail-actions"><span className={`stage-tag stage-${selectedEvent.stage}`}>{stageLabels[selectedEvent.stage]}</span><button type="button" onClick={() => copyTrace(selectedEvent.trace)}>{copiedTrace === selectedEvent.trace ? "已复制" : "复制 Trace"}</button></div>
              </div>
              <dl className="run-detail-facts">
                <div><dt>Trace ID</dt><dd><code>{selectedEvent.trace}</code></dd></div>
                <div><dt>发生时间</dt><dd>{selectedEvent.time}</dd></div>
                <div><dt>耗时</dt><dd>{selectedEvent.duration ?? "—"}</dd></div>
                <div><dt>当前状态</dt><dd className={selectedEvent.level === "ERROR" ? "status-error" : "status-ok"}>{selectedEvent.level === "ERROR" ? "失败" : "已完成"}</dd></div>
                <div><dt>会话 ID</dt><dd><code>{selectedEvent.sessionId}</code></dd></div>
                <div><dt>用户 ID</dt><dd><code>{selectedEvent.userId}</code></dd></div>
              </dl>
              <div className="run-detail-block">
                <span className="detail-label">事件说明</span>
                <p>{selectedEvent.detail}</p>
              </div>
              <div className="run-detail-block summary-grid">
                <div><span className="detail-label">输入摘要</span><p>{selectedEvent.inputSummary}</p></div>
                <div><span className="detail-label">输出摘要</span><p>{selectedEvent.outputSummary}</p></div>
              </div>
              <details className="raw-log-details">
                <summary>查看原始日志</summary>
                <pre>{selectedEvent.rawLog}</pre>
              </details>
              <div className="run-detail-block">
                <span className="detail-label">同一 Trace</span>
                <button className="trace-link" type="button">查看该 Trace 的完整时间线 →</button>
              </div>
            </>
          ) : <p className="empty-state">选择一条记录查看详情。</p>}
        </aside>
      </section>
    </div>
  );
}
