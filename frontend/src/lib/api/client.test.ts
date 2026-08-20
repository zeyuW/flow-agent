import * as client from "./client";
import {
  cancelSchedule,
  createSchedule,
  getEvents,
  getSession,
  getSchedules,
  getSessions,
  getTraces,
  resumeSchedule
} from "./client";

describe("管理 API 客户端", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("将成功响应中的损坏 JSON 映射为可读的 API 错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockRejectedValue(new SyntaxError("Unexpected end of JSON input"))
      })
    );

    await expect(getTraces()).rejects.toEqual(
      expect.objectContaining({
        name: "AdminApiError",
        message: "管理 API 返回了无效 JSON",
        status: 200
      })
    );
  });

  it("接受后端省略 error 的事件响应", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue([
        {
          type: "turn_committed",
          at: "2026-08-10T13:41:03.257527Z",
          status: "ok",
          summary: "回合已提交",
          trace_id: "79d90ffac4c3"
        }
      ])
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getEvents()).resolves.toHaveLength(1);

    const requestUrl = new URL(String(fetchMock.mock.calls[0]?.[0]), "https://control-plane.test");
    expect(requestUrl.pathname).toBe("/api/events");
  });

  it("按日期范围请求会话摘要", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue([])
    });
    vi.stubGlobal("fetch", fetchMock);

    await getSessions("2026-08-20", "2026-08-21");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions?start_date=2026-08-20&end_date=2026-08-21&limit=50",
      expect.any(Object)
    );
  });

  it("按选择日期请求会话消息", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        id: "telegram:1",
        channel: "telegram",
        external_conversation_id: "1",
        created_at: "2026-08-20T00:00:00Z",
        updated_at: "2026-08-21T00:00:00Z",
        message_count: 0,
        preview: null,
        messages: []
      })
    });
    vi.stubGlobal("fetch", fetchMock);

    await getSession("telegram:1", "2026-08-21", "2026-08-21");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/telegram%3A1?start_date=2026-08-21&end_date=2026-08-21",
      expect.any(Object)
    );
  });

  it("读取定时任务并支持停止指定任务", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue([])
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ cancelled: true })
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getSchedules()).resolves.toEqual([]);
    await expect(cancelSchedule("daily-news")).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/schedules",
      expect.any(Object)
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/schedules/daily-news/cancel",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("创建并重新启用定时任务", async () => {
    const task = {
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
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn().mockResolvedValue(task) })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ resumed: true })
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createSchedule({
        target_task_id: "daily-news",
        name: "午间提醒",
        trigger: "daily",
        when: "12:30",
        task_type: "reminder",
        message: "记得午休"
      })
    ).resolves.toEqual(task);
    await expect(resumeSchedule("daily-news")).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/schedules",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/schedules/daily-news/resume",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("只暴露已实现的管理 API 客户端", () => {
    expect(Object.keys(client).sort()).toEqual([
      "AdminApiError",
      "cancelSchedule",
      "createSchedule",
      "getEvents",
      "getSchedules",
      "getSession",
      "getSessions",
      "getTrace",
      "getTraces",
      "resumeSchedule"
    ]);
  });
});
