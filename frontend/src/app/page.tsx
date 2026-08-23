"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { MessageContent } from "@/components/message-content";
import {
  type ConsolePage,
  WorkbenchShell
} from "@/components/workbench-shell";
import {
  cancelSchedule,
  createSchedule,
  getCapabilities,
  removeMcpServer,
  saveMcpServer,
  getSchedules,
  getSession,
  getSessions,
  installSkill,
  resumeSchedule,
  scanSkills,
  setMcpServerEnabled,
  uninstallSkill
} from "@/lib/api/client";
import type { CreateScheduleInput } from "@/lib/api/client";

function formatDate(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
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

function formatDateTime(timestamp: string) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function SessionsPage() {
  const [selectedDate, setSelectedDate] = useState(() => formatDate(new Date()));
  const [selectedId, setSelectedId] = useState<string>();
  const sessionsQuery = useQuery({
    queryKey: ["sessions", selectedDate],
    queryFn: () => getSessions(selectedDate, selectedDate)
  });
  const sessions = sessionsQuery.data ?? [];
  const selectedSession =
    sessions.find((session) => session.id === selectedId) ?? sessions[0];
  const sessionQuery = useQuery({
    queryKey: ["session", selectedSession?.id, selectedDate],
    queryFn: () => getSession(selectedSession!.id, selectedDate, selectedDate),
    enabled: Boolean(selectedSession)
  });

  return (
    <>
      <section aria-label="会话日期筛选" className="session-toolbar">
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
  const queryClient = useQueryClient();
  const [isCreating, setIsCreating] = useState(false);
  const [targetTaskId, setTargetTaskId] = useState("");
  const [draft, setDraft] = useState({
    name: "",
    trigger: "after" as "after" | "at" | "daily" | "every",
    when: "10m",
    taskType: "reminder" as "reminder" | "agent",
    message: ""
  });
  const schedulesQuery = useQuery({
    queryKey: ["schedules"],
    queryFn: getSchedules
  });
  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => cancelSchedule(taskId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] })
  });
  const createMutation = useMutation<unknown, Error, CreateScheduleInput>({
    mutationFn: (input) => createSchedule(input),
    onSuccess: () => {
      setIsCreating(false);
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
    }
  });
  const resumeMutation = useMutation({
    mutationFn: (taskId: string) => resumeSchedule(taskId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] })
  });
  const schedules = schedulesQuery.data ?? [];
  const targets = schedules.filter(
    (task, index) =>
      schedules.findIndex(
        (candidate) =>
          candidate.channel === task.channel &&
          candidate.session_id === task.session_id
      ) === index
  );
  const activeTargetTaskId = targetTaskId || targets[0]?.id || "";

  function openCreateDialog() {
    setTargetTaskId(targets[0]?.id ?? "");
    setIsCreating(true);
  }

  function selectTrigger(trigger: "after" | "at" | "daily" | "every") {
    const when =
      trigger === "daily" ? "09:00" :
      trigger === "at" ? "" :
      trigger === "every" ? "1h" :
      "10m";
    setDraft((current) => ({ ...current, trigger, when }));
  }

  function createTask(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeTargetTaskId) return;
    createMutation.mutate({
      target_task_id: activeTargetTaskId,
      name: draft.name,
      trigger: draft.trigger,
      when: draft.when,
      task_type: draft.taskType,
      message: draft.message
    });
  }

  const whenLabel =
    draft.trigger === "daily" ? "每天时间" :
    draft.trigger === "at" ? "执行时间" :
    draft.trigger === "every" ? "执行间隔" :
    "等待时长";

  return (
    <>
      <div className="page-actions">
        <button onClick={openCreateDialog} type="button">
          新建任务
        </button>
      </div>
      <section className="compact-card-grid">
        {schedulesQuery.isPending ? (
        <p className="empty-state">正在读取定时任务…</p>
        ) : schedulesQuery.isError ? (
        <p className="empty-state">无法读取定时任务。</p>
        ) : schedules.length === 0 ? (
        <p className="empty-state">还没有定时任务。</p>
        ) : (
        schedules.map((task) => (
          <article className="feature-card" key={task.id}>
            <div>
              <p className="eyebrow">
                {task.enabled ? "已启用" : "已停止"} · {task.channel}
              </p>
              <h2>{task.name}</h2>
            </div>
            <p>{task.message}</p>
            <footer>
              <span>
                {task.enabled
                  ? `下次执行：${formatDateTime(task.next_run_at)}`
                  : "任务已停止"}
              </span>
              {task.enabled ? (
                <button
                  disabled={cancelMutation.isPending}
                  onClick={() => cancelMutation.mutate(task.id)}
                  type="button"
                >
                  停止任务
                </button>
              ) : task.trigger === "daily" || task.trigger === "every" ? (
                <button
                  disabled={resumeMutation.isPending}
                  onClick={() => resumeMutation.mutate(task.id)}
                  type="button"
                >
                  重新启用
                </button>
              ) : null}
            </footer>
          </article>
        ))
        )}
      </section>
      {isCreating ? (
        <div className="dialog-backdrop">
          <form className="schedule-dialog" onSubmit={createTask}>
            <header>
              <h2>新建定时任务</h2>
              <button
                aria-label="关闭新建任务"
                onClick={() => setIsCreating(false)}
                type="button"
              >
                ×
              </button>
            </header>
            {targets.length === 0 ? (
              <p className="empty-state">暂无可用投递目标。</p>
            ) : (
              <>
                <label>
                  <span>发送到</span>
                  <select
                    onChange={(event) => setTargetTaskId(event.target.value)}
                    value={activeTargetTaskId}
                  >
                    {targets.map((task) => (
                      <option key={task.id} value={task.id}>
                        {task.channel} · {task.session_id}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>任务名称</span>
                  <input
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, name: event.target.value }))
                    }
                    value={draft.name}
                  />
                </label>
                <label>
                  <span>任务类型</span>
                  <select
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        taskType: event.target.value as "reminder" | "agent"
                      }))
                    }
                    value={draft.taskType}
                  >
                    <option value="reminder">直接提醒</option>
                    <option value="agent">Agent 执行</option>
                  </select>
                </label>
                <label>
                  <span>执行方式</span>
                  <select
                    onChange={(event) =>
                      selectTrigger(
                        event.target.value as "after" | "at" | "daily" | "every"
                      )
                    }
                    value={draft.trigger}
                  >
                    <option value="after">延迟一次</option>
                    <option value="at">指定时间一次</option>
                    <option value="daily">每天</option>
                    <option value="every">固定间隔</option>
                  </select>
                </label>
                <label>
                  <span>{whenLabel}</span>
                  <input
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, when: event.target.value }))
                    }
                    placeholder={draft.trigger === "daily" ? "09:00" : "例如 10m、1h"}
                    required
                    type={
                      draft.trigger === "at" ? "datetime-local" :
                      draft.trigger === "daily" ? "time" :
                      "text"
                    }
                    value={draft.when}
                  />
                </label>
                <label>
                  <span>任务内容</span>
                  <textarea
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, message: event.target.value }))
                    }
                    required
                    value={draft.message}
                  />
                </label>
              </>
            )}
            <footer>
              <button onClick={() => setIsCreating(false)} type="button">
                取消
              </button>
              <button
                disabled={!activeTargetTaskId || createMutation.isPending}
                type="submit"
              >
                创建任务
              </button>
            </footer>
            </form>
          </div>
        ) : null}
    </>
  );
}

function CapabilitiesPage() {
  const queryClient = useQueryClient();
  const [isInstallDialogOpen, setIsInstallDialogOpen] = useState(false);
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [candidates, setCandidates] = useState<{ name: string }[] | null>(null);
  const [selectedNames, setSelectedNames] = useState<string[]>([]);
  const [isMcpDialogOpen, setIsMcpDialogOpen] = useState(false);
  const [mcpName, setMcpName] = useState("");
  const [mcpType, setMcpType] = useState<"stdio" | "http">("stdio");
  const [mcpCommand, setMcpCommand] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpArgs, setMcpArgs] = useState("");
  const [mcpCwd, setMcpCwd] = useState("");
  const [mcpEnv, setMcpEnv] = useState("");
  const [mcpHeaders, setMcpHeaders] = useState("");
  const refreshCapabilities = () =>
    queryClient.invalidateQueries({ queryKey: ["capabilities"] });
  const installMutation = useMutation({
    mutationFn: ({ url, names }: { url: string; names: string[] }) =>
      installSkill(url, names),
    onSuccess: () => {
      setRepositoryUrl("");
      setCandidates(null);
      setSelectedNames([]);
      setIsInstallDialogOpen(false);
      refreshCapabilities();
    }
  });
  const scanMutation = useMutation({
    mutationFn: (url: string) => scanSkills(url),
    onSuccess: (skills) => {
      setCandidates(skills);
      setSelectedNames(skills.map((skill) => skill.name));
    }
  });
  const uninstallMutation = useMutation({
    mutationFn: (name: string) => uninstallSkill(name),
    onSuccess: refreshCapabilities
  });
  const saveMcpMutation = useMutation({
    mutationFn: () => saveMcpServer(mcpName, {
      command: mcpType === "stdio" ? mcpCommand : "",
      url: mcpType === "http" ? mcpUrl : null,
      args: mcpType === "stdio" && mcpArgs.trim() ? mcpArgs.trim().split(/\s+/) : [],
      cwd: mcpType === "stdio" ? mcpCwd.trim() || null : null,
      env: mcpEnv.trim() ? JSON.parse(mcpEnv) : {},
      headers: mcpHeaders.trim() ? JSON.parse(mcpHeaders) : {}
    }),
    onSuccess: () => {
      setIsMcpDialogOpen(false);
      setMcpName("");
      setMcpType("stdio");
      setMcpCommand("");
      setMcpUrl("");
      setMcpArgs("");
      setMcpCwd("");
      setMcpEnv("");
      setMcpHeaders("");
      refreshCapabilities();
    }
  });
  const toggleMcpMutation = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      setMcpServerEnabled(name, enabled),
    onSuccess: refreshCapabilities
  });
  const removeMcpMutation = useMutation({
    mutationFn: (name: string) => removeMcpServer(name),
    onSuccess: refreshCapabilities
  });
  const capabilitiesQuery = useQuery({
    queryKey: ["capabilities"],
    queryFn: getCapabilities
  });
  const capabilities = capabilitiesQuery.data;

  if (capabilitiesQuery.isPending) {
    return <p className="empty-state">正在读取技能与连接器…</p>;
  }

  if (capabilitiesQuery.isError || !capabilities) {
    return <p className="empty-state">无法读取技能与连接器。</p>;
  }

  return (
    <>
      <section className="capability-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Custom skills</p>
            <h2>自定义 Skills</h2>
          </div>
          <div className="section-actions">
            <span>{capabilities.skills.length} 个 Skill</span>
            <button
              type="button"
              onClick={() => {
                setCandidates(null);
                setSelectedNames([]);
                setIsInstallDialogOpen(true);
              }}
            >
              从仓库安装
            </button>
          </div>
        </div>
        <div className="compact-card-grid">
          {capabilities.skills.length === 0 ? (
            <p className="empty-state">尚未添加项目或已安装 Skill。</p>
          ) : (
            capabilities.skills.map((skill) => (
              <article className="feature-card" key={`${skill.source}-${skill.name}`}>
                <h3>{skill.name}</h3>
                <p>{skill.description}</p>
                <footer>
                  <small>
                    {skill.source === "project" ? "项目 Skill" : "已安装 Skill"}
                    {skill.status === "conflict" ? ` · ${skill.reason}` : ""}
                  </small>
                  {skill.source === "installed" ? (
                    <button
                      type="button"
                      aria-label={`卸载 ${skill.name}`}
                      disabled={uninstallMutation.isPending}
                      onClick={() => uninstallMutation.mutate(skill.name)}
                    >
                      卸载
                    </button>
                  ) : null}
                </footer>
              </article>
            ))
          )}
        </div>
      </section>
      <section className="capability-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">MCP connectors</p>
            <h2>连接器</h2>
          </div>
          <div className="section-actions">
            <span>{capabilities.connectors.length} 个连接器</span>
            <button type="button" onClick={() => setIsMcpDialogOpen(true)}>
              添加连接器
            </button>
          </div>
        </div>
        <div className="compact-card-grid">
          {capabilities.connectors.length === 0 ? (
            <p className="empty-state">尚未连接 MCP 连接器。</p>
          ) : (
            capabilities.connectors.map((connector) => (
              <article className="feature-card" key={connector.name}>
                <h3>{connector.name}</h3>
                <p>{connector.tools.join("、") || "暂未发现工具"}</p>
                <footer>
                  <small>
                    {connector.connected ? "已连接" : connector.enabled ? "未连接" : "已禁用"} · {connector.tools.length} 个工具
                  </small>
                  <span className="card-actions">
                    <button
                      type="button"
                      aria-label={`${connector.enabled ? "禁用" : "启用"} ${connector.name}`}
                      onClick={() => toggleMcpMutation.mutate({ name: connector.name, enabled: !connector.enabled })}
                    >
                      {connector.enabled ? "禁用" : "启用"}
                    </button>
                    <button
                      type="button"
                      aria-label={`删除 ${connector.name}`}
                      onClick={() => removeMcpMutation.mutate(connector.name)}
                    >
                      删除
                    </button>
                  </span>
                </footer>
              </article>
            ))
          )}
        </div>
      </section>
      {isInstallDialogOpen ? (
        <div className="dialog-backdrop" role="presentation">
          <form
            className="schedule-dialog"
            aria-label="从仓库安装 Skill"
            onSubmit={(event) => {
              event.preventDefault();
              if (candidates === null) {
                scanMutation.mutate(repositoryUrl);
              } else {
                installMutation.mutate({ url: repositoryUrl, names: selectedNames });
              }
            }}
          >
            <header>
              <h2>从仓库安装 Skill</h2>
              <button type="button" onClick={() => setIsInstallDialogOpen(false)}>
                关闭
              </button>
            </header>
            <label>
              仓库地址
              <input
                required
                value={repositoryUrl}
                placeholder="https://github.com/owner/skill.git"
                onChange={(event) => {
                  setRepositoryUrl(event.target.value);
                  setCandidates(null);
                  setSelectedNames([]);
                }}
              />
            </label>
            {candidates ? (
              <div className="skill-picker">
                {candidates.map((skill) => (
                  <label key={skill.name}>
                    <input
                      type="checkbox"
                      aria-label={`选择 ${skill.name}`}
                      checked={selectedNames.includes(skill.name)}
                      onChange={() =>
                        setSelectedNames((names) =>
                          names.includes(skill.name)
                            ? names.filter((name) => name !== skill.name)
                            : [...names, skill.name]
                        )
                      }
                    />
                    {skill.name}
                  </label>
                ))}
              </div>
            ) : null}
            {scanMutation.isError || installMutation.isError ? (
              <p className="form-error">操作失败，请确认仓库地址和 Skill 内容。</p>
            ) : null}
            <footer>
              <button type="button" onClick={() => setIsInstallDialogOpen(false)}>
                取消
              </button>
              <button
                disabled={
                  scanMutation.isPending ||
                  installMutation.isPending ||
                  (candidates !== null && selectedNames.length === 0)
                }
                type="submit"
              >
                {candidates === null
                  ? scanMutation.isPending
                    ? "扫描中…"
                    : "扫描"
                  : installMutation.isPending
                    ? "安装中…"
                    : `安装 ${selectedNames.length} 个 Skill`}
              </button>
            </footer>
          </form>
        </div>
      ) : null}
      {isMcpDialogOpen ? (
        <div className="dialog-backdrop" role="presentation">
          <form
            className="schedule-dialog"
            aria-label="添加 MCP 连接器"
            onSubmit={(event) => {
              event.preventDefault();
              saveMcpMutation.mutate();
            }}
          >
            <header>
              <h2>添加 MCP 连接器</h2>
              <button type="button" onClick={() => setIsMcpDialogOpen(false)}>关闭</button>
            </header>
            <label>名称<input required value={mcpName} onChange={(event) => setMcpName(event.target.value)} placeholder="weather" /></label>
            <label>连接方式<select value={mcpType} onChange={(event) => setMcpType(event.target.value as "stdio" | "http")}><option value="stdio">本地 stdio</option><option value="http">远程 Streamable HTTP</option></select></label>
            {mcpType === "stdio" ? <>
              <label>启动命令<input required value={mcpCommand} onChange={(event) => setMcpCommand(event.target.value)} placeholder="npx" /></label>
              <label>参数<input value={mcpArgs} onChange={(event) => setMcpArgs(event.target.value)} placeholder="-y @example/mcp-server" /></label>
              <label>工作目录<input value={mcpCwd} onChange={(event) => setMcpCwd(event.target.value)} placeholder="可选" /></label>
            </> : <label>远程 MCP 地址<input required value={mcpUrl} onChange={(event) => setMcpUrl(event.target.value)} placeholder="https://example.com/mcp" /></label>}
            <label>环境变量（JSON）<textarea value={mcpEnv} onChange={(event) => setMcpEnv(event.target.value)} placeholder='{"API_KEY":"your-key"}' /></label>
            {mcpType === "http" ? <label>请求头（JSON）<textarea value={mcpHeaders} onChange={(event) => setMcpHeaders(event.target.value)} placeholder='{"Authorization":"Bearer ..."}' /></label> : null}
            {saveMcpMutation.isError ? <p className="form-error">连接器保存失败，请检查配置。</p> : null}
            <footer>
              <button type="button" onClick={() => setIsMcpDialogOpen(false)}>取消</button>
              <button type="submit" disabled={saveMcpMutation.isPending}>{saveMcpMutation.isPending ? "保存中…" : "保存并连接"}</button>
            </footer>
          </form>
        </div>
      ) : null}
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
