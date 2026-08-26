import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  cancelSchedule,
  createSchedule,
  getCapabilities,
  getMcpServers,
  getLogs,
  getSchedules,
  getSession,
  getSessions,
  installSkill,
  removeMcpServer,
  resumeSchedule,
  scanSkills,
  saveMcpServer,
  setMcpServerEnabled,
  uninstallSkill
} from "@/lib/api/client";

import OverviewPage from "./page";
import type { LogPage } from "@/lib/api/schemas";

vi.mock("@/lib/api/client", () => ({
  cancelSchedule: vi.fn(),
  createSchedule: vi.fn(),
  getCapabilities: vi.fn(),
  getMcpServers: vi.fn(),
  getLogs: vi.fn(),
  getSchedules: vi.fn(),
  getSession: vi.fn(),
  getSessions: vi.fn(),
  installSkill: vi.fn(),
  removeMcpServer: vi.fn(),
  resumeSchedule: vi.fn(),
  scanSkills: vi.fn(),
  saveMcpServer: vi.fn(),
  setMcpServerEnabled: vi.fn(),
  uninstallSkill: vi.fn()
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <OverviewPage />
    </QueryClientProvider>
  );
}

describe("OverviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getCapabilities).mockResolvedValue({ skills: [], connectors: [] });
    vi.mocked(getMcpServers).mockResolvedValue([]);
    vi.mocked(getLogs).mockImplementation(async (filters = {}) => {
      const items: LogPage["items"] = [
        {
          id: "proactive-1",
          at: "2026-08-25T03:28:08.579Z",
          level: "INFO" as const,
          stage: "proactive",
          title: "主动消息去重命中",
          detail: "候选消息已存在",
          trace_id: "trace-proactive",
          session_id: "telegram:1",
          error: null,
          status: "completed",
          started_at: "2026-08-25T03:28:08.000Z",
          finished_at: "2026-08-25T03:28:08.579Z",
          duration_ms: 579,
          event_count: 1,
          events: [{ type: "turn_committed", at: "2026-08-25T03:28:08.579Z", level: "INFO" as const, title: "主动消息去重命中", detail: "候选消息已存在", error: null }]
        },
        {
          id: "memory-1",
          at: "2026-08-25T03:27:33.619Z",
          level: "INFO" as const,
          stage: "memory",
          title: "画像归档模型调用完成",
          detail: "处理待归档事实",
          trace_id: "trace-memory",
          session_id: "memory:background",
          error: null,
          status: "completed",
          started_at: "2026-08-25T03:27:33.000Z",
          finished_at: "2026-08-25T03:27:33.619Z",
          duration_ms: 619,
          event_count: 1,
          events: [{ type: "turn_committed", at: "2026-08-25T03:27:33.619Z", level: "INFO" as const, title: "画像归档模型调用完成", detail: "处理待归档事实", error: null }]
        }
      ].filter((item) => !filters.stage || item.stage === filters.stage);
      return { items, total: items.length, limit: 5, offset: 0 };
    });
    vi.mocked(getSchedules).mockResolvedValue([]);
    vi.mocked(cancelSchedule).mockResolvedValue(undefined);
    vi.mocked(createSchedule).mockResolvedValue({
      id: "new-task",
      name: "午间提醒",
      trigger: "daily",
      task_type: "reminder",
      message: "记得午休",
      channel: "telegram",
      session_id: "telegram:1",
      timezone: "Asia/Shanghai",
      next_run_at: "2026-08-22T04:30:00Z",
      interval_seconds: null,
      daily_time: "12:30",
      enabled: true,
      run_count: 0,
      created_at: "2026-08-21T00:00:00Z",
      last_error: null
    });
    vi.mocked(resumeSchedule).mockResolvedValue(undefined);
    vi.mocked(scanSkills).mockResolvedValue([{ name: "daily-brief" }]);
    vi.mocked(installSkill).mockResolvedValue([{ name: "daily-brief" }]);
    vi.mocked(uninstallSkill).mockResolvedValue(undefined);
    vi.mocked(removeMcpServer).mockResolvedValue(undefined);
    vi.mocked(saveMcpServer).mockResolvedValue({ name: "weather", enabled: true, connected: false, tools: [] });
    vi.mocked(setMcpServerEnabled).mockResolvedValue(undefined);
    vi.mocked(getSessions).mockResolvedValue([]);
    vi.mocked(getSession).mockResolvedValue({
      id: "telegram:1",
      channel: "telegram",
      external_conversation_id: "1",
      created_at: "2026-08-21T02:00:00Z",
      updated_at: "2026-08-21T02:00:00Z",
      message_count: 0,
      preview: null,
      messages: []
    });
  });

  it("展示连接器状态并支持禁用", async () => {
    vi.mocked(getCapabilities).mockResolvedValueOnce({
      skills: [],
      connectors: [{ name: "weather", enabled: true, connected: true, tools: ["forecast"] }]
    });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "技能与连接器" }));

    expect(await screen.findByText("weather")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "禁用 weather" }));
    await waitFor(() => expect(setMcpServerEnabled).toHaveBeenCalledWith("weather", false));
  });

  it("展示运行记录并支持按业务阶段筛选", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "日志" }));

    expect(await screen.findByLabelText("运行记录筛选")).toBeInTheDocument();
    expect((await screen.findAllByText("主动消息去重命中")).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("业务阶段"), { target: { value: "memory" } });

    expect((await screen.findAllByText("画像归档模型调用完成")).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.queryByText("主动消息去重命中")).not.toBeInTheDocument());
  });

  it("展示连接器协议版本和连接失败原因", async () => {
    vi.mocked(getCapabilities).mockResolvedValueOnce({
      skills: [],
      connectors: [{
        name: "mcp-docs",
        enabled: true,
        connected: false,
        transport: "http",
        protocol_version: "2026-07-28",
        tools: [],
        error: "远程 MCP 返回 401"
      }]
    });

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "技能与连接器" }));

    expect(await screen.findByText("mcp-docs")).toBeInTheDocument();
    expect(screen.getByText("远程 MCP 返回 401")).toBeInTheDocument();
  });

  it("只保留日期选择器，不显示快捷日期筛选", async () => {
    renderPage();

    expect(screen.getByLabelText("选择日期")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "今天" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "昨天" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "近 7 天" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("选择日期"), {
      target: { value: "2026-08-21" }
    });
    await waitFor(() =>
      expect(getSessions).toHaveBeenCalledWith("2026-08-21", "2026-08-21")
    );
  });

  it("选中真实会话后显示 Agent 消息与工具链", async () => {
    vi.mocked(getSessions).mockResolvedValueOnce([
      {
        id: "telegram:1",
        channel: "telegram",
        external_conversation_id: "1",
        created_at: "2026-08-21T02:00:00Z",
        updated_at: "2026-08-21T02:00:00Z",
        message_count: 2,
        preview: "你好"
      }
    ]);
    vi.mocked(getSession).mockResolvedValueOnce({
      id: "telegram:1",
      channel: "telegram",
      external_conversation_id: "1",
      created_at: "2026-08-21T02:00:00Z",
      updated_at: "2026-08-21T02:00:00Z",
      message_count: 2,
      preview: "你好",
      messages: [
        {
          role: "assistant",
          content: "你好，有什么可以帮你？",
          timestamp: "2026-08-21T02:00:01Z",
          tool_chain: ["search"]
        }
      ]
    });

    renderPage();

    expect(await screen.findByText("你好，有什么可以帮你？")).toBeInTheDocument();
    expect(screen.getByText("search")).toBeInTheDocument();
  });

  it("将用户与 Agent 消息渲染为可读的 Markdown", async () => {
    vi.mocked(getSessions).mockResolvedValueOnce([
      {
        id: "telegram:1",
        channel: "telegram",
        external_conversation_id: "1",
        created_at: "2026-08-21T02:00:00Z",
        updated_at: "2026-08-21T02:00:00Z",
        message_count: 2,
        preview: "今日资讯"
      }
    ]);
    vi.mocked(getSession).mockResolvedValueOnce({
      id: "telegram:1",
      channel: "telegram",
      external_conversation_id: "1",
      created_at: "2026-08-21T02:00:00Z",
      updated_at: "2026-08-21T02:00:00Z",
      message_count: 2,
      preview: "今日资讯",
      messages: [
        {
          role: "user",
          content: "请看 [原文](https://example.com)",
          timestamp: "2026-08-21T02:00:00Z",
          tool_chain: []
        },
        {
          role: "assistant",
          content: "## 今日资讯\n\n- [Threads](https://example.com/threads)",
          timestamp: "2026-08-21T02:00:01Z",
          tool_chain: []
        }
      ]
    });

    renderPage();

    expect(await screen.findByRole("heading", { name: "今日资讯" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "原文" })).toHaveAttribute(
      "href",
      "https://example.com"
    );
    expect(screen.getByText(/用户/)).toBeInTheDocument();
  });

  it("展示真实定时任务并允许停止", async () => {
    vi.mocked(getSchedules).mockResolvedValueOnce([
      {
        id: "daily-news",
        name: "晨间简报",
        trigger: "daily",
        task_type: "agent",
        message: "汇总今天的重要资讯",
        channel: "telegram",
        session_id: "telegram:1",
        timezone: "Asia/Shanghai",
        next_run_at: "2026-08-22T00:30:00Z",
        interval_seconds: null,
        daily_time: "08:30",
        enabled: true,
        run_count: 3,
        created_at: "2026-08-21T00:00:00Z",
        last_error: null
      }
    ]);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "定时任务" }));

    expect(await screen.findByText("晨间简报")).toBeInTheDocument();
    expect(screen.getByText("汇总今天的重要资讯")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "停止任务" }));
    await waitFor(() =>
      expect(cancelSchedule).toHaveBeenCalledWith("daily-news")
    );
  });

  it("可从定时任务页创建任务", async () => {
    vi.mocked(getSchedules).mockResolvedValueOnce([
      {
        id: "daily-news",
        name: "每日新闻",
        trigger: "daily",
        task_type: "agent",
        message: "推送新闻",
        channel: "telegram",
        session_id: "telegram:1",
        timezone: "Asia/Shanghai",
        next_run_at: "2026-08-22T00:00:00Z",
        interval_seconds: null,
        daily_time: "08:00",
        enabled: true,
        run_count: 0,
        created_at: "2026-08-21T00:00:00Z",
        last_error: null
      }
    ]);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "定时任务" }));
    fireEvent.click(await screen.findByRole("button", { name: "新建任务" }));
    fireEvent.change(screen.getByLabelText("任务名称"), {
      target: { value: "午间提醒" }
    });
    fireEvent.change(screen.getByLabelText("任务内容"), {
      target: { value: "记得午休" }
    });
    fireEvent.click(screen.getByRole("button", { name: "创建任务" }));

    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith({
        target_task_id: "daily-news",
        name: "午间提醒",
        trigger: "after",
        when: "10m",
        task_type: "reminder",
        message: "记得午休"
      })
    );
  });

  it("只有一个投递目标时不显示重复的目标下拉框", async () => {
    vi.mocked(getSchedules).mockResolvedValueOnce([
      {
        id: "daily-news",
        name: "每日新闻",
        trigger: "daily",
        task_type: "agent",
        message: "推送新闻",
        channel: "telegram",
        session_id: "telegram:1",
        timezone: "Asia/Shanghai",
        next_run_at: "2026-08-22T00:00:00Z",
        interval_seconds: null,
        daily_time: "08:00",
        enabled: true,
        run_count: 0,
        created_at: "2026-08-21T00:00:00Z",
        last_error: null
      }
    ]);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "定时任务" }));
    fireEvent.click(await screen.findByRole("button", { name: "新建任务" }));

    expect(screen.getByText("telegram · 1")).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(2);
  });

  it("不同内部会话键格式不能产生重复投递目标", async () => {
    vi.mocked(getSchedules).mockResolvedValueOnce([
      {
        id: "task-1", name: "提醒一", trigger: "daily", task_type: "reminder", message: "一",
        channel: "telegram", session_id: "telegram:1", timezone: "Asia/Shanghai",
        next_run_at: "2026-08-22T00:00:00Z", interval_seconds: null, daily_time: "08:00",
        enabled: true, run_count: 0, created_at: "2026-08-21T00:00:00Z", last_error: null
      },
      {
        id: "task-2", name: "提醒二", trigger: "daily", task_type: "reminder", message: "二",
        channel: "telegram", session_id: "1", timezone: "Asia/Shanghai",
        next_run_at: "2026-08-22T00:00:00Z", interval_seconds: null, daily_time: "09:00",
        enabled: true, run_count: 0, created_at: "2026-08-21T00:00:00Z", last_error: null
      }
    ]);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "定时任务" }));
    fireEvent.click(await screen.findByRole("button", { name: "新建任务" }));

    expect(screen.getByText("telegram · 1")).toBeInTheDocument();
    expect(screen.getAllByText("telegram · 1")).toHaveLength(1);
  });

  it("每天任务使用合法的时间选择器", async () => {
    vi.mocked(getSchedules).mockResolvedValueOnce([
      {
        id: "daily-news",
        name: "每日新闻",
        trigger: "daily",
        task_type: "agent",
        message: "推送新闻",
        channel: "telegram",
        session_id: "telegram:1",
        timezone: "Asia/Shanghai",
        next_run_at: "2026-08-22T00:00:00Z",
        interval_seconds: null,
        daily_time: "08:00",
        enabled: true,
        run_count: 0,
        created_at: "2026-08-21T00:00:00Z",
        last_error: null
      }
    ]);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "定时任务" }));
    fireEvent.click(await screen.findByRole("button", { name: "新建任务" }));
    fireEvent.change(screen.getByLabelText("执行方式"), {
      target: { value: "daily" }
    });

    expect(screen.getByLabelText("每天时间")).toHaveAttribute("type", "time");
  });

  it("可重新启用已停止的周期任务", async () => {
    vi.mocked(getSchedules).mockResolvedValueOnce([
      {
        id: "daily-news",
        name: "每日新闻",
        trigger: "daily",
        task_type: "agent",
        message: "推送新闻",
        channel: "telegram",
        session_id: "telegram:1",
        timezone: "Asia/Shanghai",
        next_run_at: "2026-08-22T00:00:00Z",
        interval_seconds: null,
        daily_time: "08:00",
        enabled: false,
        run_count: 2,
        created_at: "2026-08-21T00:00:00Z",
        last_error: null
      }
    ]);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "定时任务" }));
    expect(await screen.findByText("每日新闻")).toBeInTheDocument();
    expect(screen.queryByText("任务已停止")).not.toBeInTheDocument();
    expect(screen.getByText(/下次执行：08\/22 08:00/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "启动任务" }));

    await waitFor(() => expect(resumeSchedule).toHaveBeenCalledWith("daily-news"));
  });

  it("可重新启用尚未到期的一次性任务", async () => {
    vi.mocked(getSchedules).mockResolvedValueOnce([
      {
        id: "water-reminder", name: "喝水提醒", trigger: "after", task_type: "reminder",
        message: "喝水", channel: "telegram", session_id: "telegram:1", timezone: "Asia/Shanghai",
        next_run_at: new Date(Date.now() + 60_000).toISOString(), interval_seconds: null,
        daily_time: null, enabled: false, run_count: 0, created_at: "2026-08-21T00:00:00Z", last_error: null
      }
    ]);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "定时任务" }));
    fireEvent.click(await screen.findByRole("button", { name: "启动任务" }));

    await waitFor(() => expect(resumeSchedule).toHaveBeenCalledWith("water-reminder"));
  });

  it("展示项目和已安装 Skill 及连接器状态", async () => {
    vi.mocked(getCapabilities).mockResolvedValueOnce({
      skills: [
        {
          name: "weekly-report",
          description: "项目周报",
          source: "project",
          status: "available",
          reason: null
        },
        {
          name: "personal-notes",
          description: "个人笔记",
          source: "installed",
          status: "available",
          reason: null
        }
      ],
      connectors: [{ name: "ai-news", connected: true, transport: "stdio", protocol_version: "2024-11-05", tools: ["news_search"] }]
    });

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "技能与连接器" }));

    expect(await screen.findByText("weekly-report")).toBeInTheDocument();
    expect(screen.getByText("项目 Skill")).toBeInTheDocument();
    expect(screen.getByText("已安装 Skill")).toBeInTheDocument();
    expect(screen.getByText("关联 Skill：无")).toBeInTheDocument();
  });

  it("扫描、选择、安装并卸载已安装 Skill", async () => {
    vi.mocked(getCapabilities).mockResolvedValueOnce({
      skills: [
        {
          name: "personal-notes",
          description: "个人笔记",
          source: "installed",
          status: "available",
          reason: null
        }
      ],
      connectors: []
    });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "技能与连接器" }));

    fireEvent.click(await screen.findByRole("button", { name: "卸载 personal-notes" }));
    await waitFor(() => expect(uninstallSkill).toHaveBeenCalledWith("personal-notes"));
    fireEvent.click(await screen.findByRole("button", { name: "从仓库安装" }));
    fireEvent.change(screen.getByLabelText("仓库地址"), {
      target: { value: "https://github.com/acme/daily-brief.git" }
    });
    fireEvent.click(screen.getByRole("button", { name: "扫描" }));

    await waitFor(() =>
      expect(scanSkills).toHaveBeenCalledWith("https://github.com/acme/daily-brief.git")
    );
    fireEvent.click(await screen.findByLabelText("选择 daily-brief"));
    fireEvent.click(screen.getByRole("button", { name: "安装 0 个 Skill" }));

    expect(installSkill).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("选择 daily-brief"));
    fireEvent.click(screen.getByRole("button", { name: "安装 1 个 Skill" }));

    await waitFor(() =>
      expect(installSkill).toHaveBeenCalledWith(
        "https://github.com/acme/daily-brief.git",
        ["daily-brief"]
      )
    );
  });
});
