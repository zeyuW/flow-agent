"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { MessageContent } from "@/components/message-content";
import {
  type ConsolePage,
  WorkbenchShell
} from "@/components/workbench-shell";
import { getSession, getSessions } from "@/lib/api/client";

const dateFilters = [
  { id: "today", label: "今天" },
  { id: "yesterday", label: "昨天" },
  { id: "recent", label: "近 7 天" }
] as const;

type DateFilter = (typeof dateFilters)[number]["id"];

function formatDate(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function getDateRange(dateFilter: DateFilter, selectedDate: string) {
  if (selectedDate) {
    return { startDate: selectedDate, endDate: selectedDate };
  }
  const end = new Date();
  const start = new Date(end);
  if (dateFilter === "yesterday") {
    start.setDate(start.getDate() - 1);
    end.setDate(end.getDate() - 1);
  }
  if (dateFilter === "recent") {
    start.setDate(start.getDate() - 6);
  }
  return { startDate: formatDate(start), endDate: formatDate(end) };
}

function formatTime(timestamp: string) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function SessionsPage() {
  const [dateFilter, setDateFilter] = useState<DateFilter>("recent");
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedId, setSelectedId] = useState<string>();
  const dateRange = useMemo(
    () => getDateRange(dateFilter, selectedDate),
    [dateFilter, selectedDate]
  );
  const sessionsQuery = useQuery({
    queryKey: ["sessions", dateRange.startDate, dateRange.endDate],
    queryFn: () => getSessions(dateRange.startDate, dateRange.endDate)
  });
  const sessions = sessionsQuery.data ?? [];
  const selectedSession =
    sessions.find((session) => session.id === selectedId) ?? sessions[0];
  const sessionQuery = useQuery({
    queryKey: ["session", selectedSession?.id],
    queryFn: () => getSession(selectedSession!.id),
    enabled: Boolean(selectedSession)
  });

  return (
    <>
      <section aria-label="会话日期筛选" className="session-toolbar">
        <div className="date-filter-list">
          {dateFilters.map((filter) => (
            <button
              aria-pressed={!selectedDate && dateFilter === filter.id}
              key={filter.id}
              onClick={() => {
                setDateFilter(filter.id);
                setSelectedDate("");
              }}
              type="button"
            >
              {filter.label}
            </button>
          ))}
        </div>
        <label className="date-picker">
          <span>选择日期</span>
          <input
            aria-label="选择日期"
            onChange={(event) => setSelectedDate(event.target.value)}
            type="date"
            value={selectedDate}
          />
        </label>
      </section>
      <section className="conversation-workspace">
        <aside aria-label="会话列表" className="conversation-list">
          {sessionsQuery.isPending ? (
            <p className="empty-state">正在读取会话…</p>
          ) : sessionsQuery.isError ? (
            <p className="empty-state">无法读取会话记录。</p>
          ) : sessions.length === 0 ? (
            <p className="empty-state">这个日期没有会话记录。</p>
          ) : (
            sessions.map((session) => (
              <button
                className={
                  session.id === selectedSession?.id
                    ? "conversation-item conversation-item-selected"
                    : "conversation-item"
                }
                key={session.id}
                onClick={() => setSelectedId(session.id)}
                type="button"
              >
                <span className="conversation-item-title">
                  <strong>{session.external_conversation_id}</strong>
                  <small>{session.channel}</small>
                </span>
                <span>{session.preview ?? "暂无消息"}</span>
                <time>{formatTime(session.updated_at)}</time>
              </button>
            ))
          )}
        </aside>
        <section aria-label="对话内容" className="chat-panel">
          {selectedSession ? (
            <>
              <header className="chat-header">
                <div>
                  <h2>{selectedSession.external_conversation_id}</h2>
                  <p>
                    {selectedSession.channel} · {selectedSession.updated_at.slice(0, 10)}
                  </p>
                </div>
                <span>历史会话</span>
              </header>
              {sessionQuery.isPending ? (
                <p className="empty-state">正在读取对话…</p>
              ) : sessionQuery.isError ? (
                <p className="empty-state">无法读取该会话。</p>
              ) : (
                <div className="message-list">
                  {sessionQuery.data?.messages.map((message, index) => (
                  <article
                    className={`message message-${message.role === "assistant" ? "agent" : "user"}`}
                    key={`${message.timestamp}-${index}`}
                  >
                    <p className="message-label">
                      {message.role === "user" ? "用户" : "Agent"} · {formatTime(message.timestamp)}
                    </p>
                    <MessageContent content={message.content} />
                    {message.tool_chain.length > 0 ? (
                      <div className="turn-summary">
                        <div>
                          {message.tool_chain.map((tool) => (
                            <small key={tool}>{tool}</small>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </article>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="empty-state">选择一条会话查看对话内容。</p>
          )}
        </section>
      </section>
    </>
  );
}

function SchedulesPage() {
  return (
    <>
      <section className="compact-card-grid">
        <article className="feature-card">
          <div>
            <p className="eyebrow">已启用</p>
            <h2>晨间简报</h2>
          </div>
          <p>工作日上午 08:30 汇总日程、待办与关注事项。</p>
          <footer>
            <span>下次执行：明天 08:30</span>
            <button type="button">查看任务</button>
          </footer>
        </article>
        <article className="feature-card">
          <div>
            <p className="eyebrow">已启用</p>
            <h2>会议准备提醒</h2>
          </div>
          <p>在会议开始前 30 分钟提醒准备所需材料。</p>
          <footer>
            <span>下次执行：今天 14:30</span>
            <button type="button">查看任务</button>
          </footer>
        </article>
      </section>
    </>
  );
}

function CapabilitiesPage() {
  return (
    <>
      <section className="capability-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Custom skills</p>
            <h2>自定义 Skills</h2>
          </div>
          <span>2 个已加载</span>
        </div>
        <div className="compact-card-grid">
          <article className="feature-card">
            <h3>项目周报</h3>
            <p>收集进展、阻塞事项并输出结构化周报。</p>
            <small>本地 Skill</small>
          </article>
          <article className="feature-card">
            <h3>资料研究</h3>
            <p>检索、阅读和归纳多来源资料。</p>
            <small>本地 Skill</small>
          </article>
        </div>
      </section>
      <section className="capability-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">MCP connectors</p>
            <h2>连接器</h2>
          </div>
          <span>2 个已连接</span>
        </div>
        <div className="compact-card-grid">
          <article className="feature-card">
            <h3>日程</h3>
            <p>读取日历事件并创建提醒。</p>
            <small>已连接</small>
          </article>
          <article className="feature-card">
            <h3>网页研究</h3>
            <p>为 Agent 提供受控的信息检索能力。</p>
            <small>已连接</small>
          </article>
        </div>
      </section>
    </>
  );
}

function PluginsPage() {
  return (
    <>
      <section className="compact-card-grid">
        <article className="feature-card">
          <div>
            <p className="eyebrow">已启用 · v1.0.0</p>
            <h2>工作区助手</h2>
          </div>
          <p>在每轮对话开始前补充项目上下文，并记录回合结果。</p>
          <footer>
            <span>生命周期插件</span>
            <button type="button">查看详情</button>
          </footer>
        </article>
        <article className="feature-card">
          <div>
            <p className="eyebrow">准备中</p>
            <h2>自动化扩展</h2>
          </div>
          <p>用于未来接入外部任务、通知和领域工作流。</p>
          <footer>
            <span>尚未启用</span>
            <button type="button">查看详情</button>
          </footer>
        </article>
      </section>
    </>
  );
}

export default function OverviewPage() {
  const [activePage, setActivePage] = useState<ConsolePage>("sessions");
  const content =
    activePage === "sessions" ? <SessionsPage /> :
    activePage === "schedules" ? <SchedulesPage /> :
    activePage === "capabilities" ? <CapabilitiesPage /> :
    <PluginsPage />;

  return (
    <WorkbenchShell
      activePage={activePage}
      header={<ThemeToggle />}
      onNavigate={setActivePage}
    >
      {content}
    </WorkbenchShell>
  );
}
