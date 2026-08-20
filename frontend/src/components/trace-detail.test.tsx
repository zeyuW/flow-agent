import { render, screen } from "@testing-library/react";

import { TraceDetailPanel } from "./trace-detail";

describe("TraceDetailPanel", () => {
  it("展示 trace 的事件时间线与错误信息", () => {
    render(
      <TraceDetailPanel
        trace={{
          id: "79d90ffac4c3",
          channel: "telegram",
          status: "failed",
          started_at: "2026-08-10T13:41:00.957441Z",
          duration_ms: 2300,
          finished_at: "2026-08-10T13:41:03.257527Z",
          error: "下游投递失败",
          events: [
            { type: "turn_started", at: "2026-08-10T13:41:00.957441Z", status: "ok", summary: "收到渠道消息", error: null }
          ]
        }}
      />
    );

    expect(screen.getByText("下游投递失败")).toBeVisible();
    expect(screen.getByText("收到渠道消息")).toBeVisible();
  });

  it("将空开始时间显示为尚未开始", () => {
    render(
      <TraceDetailPanel
        trace={{
          id: "trace-queued",
          channel: "telegram",
          status: "running",
          started_at: null,
          duration_ms: 0,
          finished_at: null,
          error: null,
          events: []
        }}
      />
    );

    expect(screen.getByText("尚未开始")).toBeVisible();
  });
});
