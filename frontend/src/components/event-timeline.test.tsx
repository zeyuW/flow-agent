import { fireEvent, render, screen } from "@testing-library/react";

import { EventTimeline } from "./event-timeline";

describe("EventTimeline", () => {
  it("点击带 trace_id 的事件会选择对应 Trace", () => {
    const onSelectTrace = vi.fn();

    render(
      <EventTimeline
        events={[
          {
            type: "turn_committed",
            at: "2026-08-10T13:41:03.257527Z",
            status: "ok",
            summary: "回合已提交",
            error: null,
            trace_id: "79d90ffac4c3"
          }
        ]}
        onSelectTrace={onSelectTrace}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /回合已提交/ }));

    expect(onSelectTrace).toHaveBeenCalledWith("79d90ffac4c3");
  });
});
