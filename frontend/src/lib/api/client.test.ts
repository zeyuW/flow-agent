import * as client from "./client";
import { getEvents, getSessions, getTraces } from "./client";

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

  it("只暴露已实现的管理 API 客户端", () => {
    expect(Object.keys(client).sort()).toEqual([
      "AdminApiError",
      "getEvents",
      "getSession",
      "getSessions",
      "getTrace",
      "getTraces"
    ]);
  });
});
