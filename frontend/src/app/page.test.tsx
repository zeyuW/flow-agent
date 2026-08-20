import { render, screen } from "@testing-library/react";

import OverviewPage from "./page";

describe("OverviewPage", () => {
  it("不在内容区重复显示当前导航页的标题和说明", () => {
    render(<OverviewPage />);

    expect(screen.queryByRole("heading", { name: "会话" })).not.toBeInTheDocument();
    expect(screen.queryByText("Agent conversations")).not.toBeInTheDocument();
    expect(
      screen.queryByText("查看用户与 Agent 的历史对话。当前为界面示例数据。")
    ).not.toBeInTheDocument();
  });
});
