import { render, screen } from "@testing-library/react";

import { StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
  it("显示未知状态的文字标签", () => {
    render(<StatusBadge status="unknown" />);

    expect(screen.getByText("状态未知")).toBeVisible();
  });
});
