import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { WorkbenchShell } from "./workbench-shell";

describe("WorkbenchShell", () => {
  it("只展示面向 Agent 的四个一级入口", () => {
    render(
      <WorkbenchShell
        activePage="sessions"
        header={<span>header</span>}
        onNavigate={vi.fn()}
      >
        <p>content</p>
      </WorkbenchShell>
    );

    expect(screen.getByRole("button", { name: "会话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "定时任务" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "技能与连接器" })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "插件" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "概览" })).not.toBeInTheDocument();
  });
});
