"use client";

import { useMemo, useState } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import {
  type ConsolePage,
  WorkbenchShell
} from "@/components/workbench-shell";

type Conversation = {
  channel: string;
  date: string;
  dateLabel: string;
  id: string;
  messages: Array<{
    content: string;
    meta?: string;
    role: "agent" | "user";
    time: string;
    tools?: string[];
  }>;
  preview: string;
  title: string;
};

const conversations: Conversation[] = [
  {
    channel: "Telegram",
    date: "2026-08-21",
    dateLabel: "今天",
    id: "morning-brief",
    preview: "帮我整理今天需要关注的内容",
    title: "晨间规划",
    messages: [
      { content: "帮我整理今天需要关注的内容。", role: "user", time: "10:24" },
      {
        content:
          "我已按优先级整理出今天的待办：先完成项目联调，再查看下午的日程安排。",
        meta: "本轮处理完成 · 1.2 秒",
        role: "agent",
        time: "10:24",
        tools: ["日程连接器", "长期记忆"]
      },
      { content: "下午三点提醒我准备会议材料。", role: "user", time: "10:26" },
      {
        content: "已创建提醒。我会在下午 2:30 提前通知你准备材料。",
        meta: "已创建定时任务",
        role: "agent",
        time: "10:26",
        tools: ["定时任务"]
      }
    ]
  },
  {
    channel: "HTTP",
    date: "2026-08-21",
    dateLabel: "今天",
    id: "research",
    preview: "总结这份资料的核心结论",
    title: "资料研究",
    messages: [
      { content: "总结这份资料的核心结论。", role: "user", time: "09:48" },
      {
        content: "内容主要围绕 Agent 的长期记忆、工具调用边界和可观测性展开。",
        meta: "本轮处理完成 · 2.1 秒",
        role: "agent",
        time: "09:48",
        tools: ["文档连接器"]
      }
    ]
  },
  {
    channel: "CLI",
    date: "2026-08-20",
    dateLabel: "昨天",
    id: "weekly-review",
    preview: "帮我回顾本周完成的事项",
    title: "本周回顾",
    messages: [
      { content: "帮我回顾本周完成的事项。", role: "user", time: "21:12" },
      {
        content: "本周你完成了控制台联调、Trace 追踪验证和运行脚本的整理。",
        meta: "本轮处理完成 · 1.7 秒",
        role: "agent",
        time: "21:12",
        tools: ["长期记忆"]
      }
    ]
  }
];

const dateFilters = [
  { id: "today", label: "今天" },
  { id: "yesterday", label: "昨天" },
  { id: "recent", label: "近 7 天" }
] as const;

type DateFilter = (typeof dateFilters)[number]["id"];

function SessionsPage() {
  const [dateFilter, setDateFilter] = useState<DateFilter>("recent");
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedId, setSelectedId] = useState(conversations[0].id);
  const visibleConversations = useMemo(() => {
    if (selectedDate) {
      return conversations.filter((conversation) => conversation.date === selectedDate);
    }
    if (dateFilter === "today") {
      return conversations.filter((conversation) => conversation.dateLabel === "今天");
    }
    if (dateFilter === "yesterday") {
      return conversations.filter((conversation) => conversation.dateLabel === "昨天");
    }
    return conversations;
  }, [dateFilter, selectedDate]);
  const selectedConversation =
    visibleConversations.find((conversation) => conversation.id === selectedId) ??
    visibleConversations[0];

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
          {visibleConversations.length === 0 ? (
            <p className="empty-state">这个日期没有会话记录。</p>
          ) : (
            visibleConversations.map((conversation) => (
              <button
                className={
                  conversation.id === selectedConversation?.id
                    ? "conversation-item conversation-item-selected"
                    : "conversation-item"
                }
                key={conversation.id}
                onClick={() => setSelectedId(conversation.id)}
                type="button"
              >
                <span className="conversation-item-title">
                  <strong>{conversation.title}</strong>
                  <small>{conversation.channel}</small>
                </span>
                <span>{conversation.preview}</span>
                <time>
                  {conversation.dateLabel} · {conversation.messages.at(-1)?.time}
                </time>
              </button>
            ))
          )}
        </aside>
        <section aria-label="对话内容" className="chat-panel">
          {selectedConversation ? (
            <>
              <header className="chat-header">
                <div>
                  <h2>{selectedConversation.title}</h2>
                  <p>
                    {selectedConversation.channel} · {selectedConversation.date}
                  </p>
                </div>
                <span>历史会话</span>
              </header>
              <div className="message-list">
                {selectedConversation.messages.map((message, index) => (
                  <article
                    className={`message message-${message.role}`}
                    key={`${message.time}-${index}`}
                  >
                    <p className="message-label">
                      {message.role === "user" ? "用户" : "Agent"} · {message.time}
                    </p>
                    <p>{message.content}</p>
                    {message.tools ? (
                      <div className="turn-summary">
                        <span>{message.meta}</span>
                        <div>
                          {message.tools.map((tool) => (
                            <small key={tool}>{tool}</small>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
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
