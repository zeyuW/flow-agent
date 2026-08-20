import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import { getSession, getSessions } from "@/lib/api/client";

import OverviewPage from "./page";

vi.mock("@/lib/api/client", () => ({
  getSession: vi.fn(),
  getSessions: vi.fn()
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

  it("不在内容区重复显示当前导航页的标题和说明", () => {
    renderPage();

    expect(screen.queryByRole("heading", { name: "会话" })).not.toBeInTheDocument();
    expect(screen.queryByText("Agent conversations")).not.toBeInTheDocument();
    expect(
      screen.queryByText("查看用户与 Agent 的历史对话。当前为界面示例数据。")
    ).not.toBeInTheDocument();
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
});
