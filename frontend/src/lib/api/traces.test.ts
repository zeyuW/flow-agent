import { getTrace, getTraces } from "./client";

describe("Trace API 客户端", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("从实际的 trace 列表接口读取裸数组", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue([
        {
          id: "79d90ffac4c3",
          channel: "telegram",
          status: "completed",
          started_at: "2026-08-10T13:41:00.957441Z",
          duration_ms: 2300
        }
      ])
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getTraces()).resolves.toHaveLength(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/traces");
  });

  it("接受尚未开始的 Trace", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue([
          {
            id: "trace-queued",
            channel: "telegram",
            status: "running",
            started_at: null,
            duration_ms: 0
          }
        ])
      })
    );

    await expect(getTraces()).resolves.toMatchObject([
      { id: "trace-queued", started_at: null }
    ]);
  });

  it("读取指定 trace 的事件时间线", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({
          id: "79d90ffac4c3",
          channel: "telegram",
          status: "completed",
          started_at: "2026-08-10T13:41:00.957441Z",
          duration_ms: 2300,
          finished_at: "2026-08-10T13:41:03.257527Z",
          error: null,
          events: [
            {
              type: "turn_started",
              at: "2026-08-10T13:41:00.957441Z",
              status: "ok",
              summary: "收到渠道消息",
              error: null
            }
          ]
        })
      })
    );

    await expect(getTrace("79d90ffac4c3")).resolves.toMatchObject({
      id: "79d90ffac4c3",
      events: [{ summary: "收到渠道消息" }]
    });
  });
});
