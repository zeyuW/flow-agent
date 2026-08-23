import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  cancelSchedule,
  createSchedule,
  getCapabilities,
  getSchedules,
  getSession,
  getSessions,
  installSkill,
  resumeSchedule,
  scanSkills,
  uninstallSkill
} from "@/lib/api/client";

import OverviewPage from "./page";

vi.mock("@/lib/api/client", () => ({
  cancelSchedule: vi.fn(),
  createSchedule: vi.fn(),
  getCapabilities: vi.fn(),
  getSchedules: vi.fn(),
  getSession: vi.fn(),
  getSessions: vi.fn(),
  installSkill: vi.fn(),
  resumeSchedule: vi.fn(),
  scanSkills: vi.fn(),
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
    vi.mocked(getCapabilities).mockResolvedValue({ skills: [], connectors: [] });
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
    fireEvent.click(await screen.findByRole("button", { name: "重新启用" }));

    await waitFor(() => expect(resumeSchedule).toHaveBeenCalledWith("daily-news"));
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
      connectors: [{ name: "ai-news", connected: true, tools: ["news_search"] }]
    });

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "技能与连接器" }));

    expect(await screen.findByText("weekly-report")).toBeInTheDocument();
    expect(screen.getByText("项目 Skill")).toBeInTheDocument();
    expect(screen.getByText("已安装 Skill")).toBeInTheDocument();
    expect(screen.getByText("已连接 · 1 个工具")).toBeInTheDocument();
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
