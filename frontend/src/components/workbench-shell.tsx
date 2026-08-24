import Link from "next/link";
import type { ReactNode } from "react";

export type ConsolePage = "sessions" | "schedules" | "capabilities" | "plugins" | "runs";

const navigation: Array<{ id: ConsolePage; label: string }> = [
  { id: "sessions", label: "会话" },
  { id: "schedules", label: "定时任务" },
  { id: "capabilities", label: "技能与连接器" },
  { id: "plugins", label: "插件" },
  { id: "runs", label: "日志" }
];

export function WorkbenchShell({
  activePage,
  children,
  header,
  onNavigate
}: {
  activePage: ConsolePage;
  children: ReactNode;
  header: ReactNode;
  onNavigate: (page: ConsolePage) => void;
}) {
  return (
    <div className="workbench">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span>FLOW</span>
          <strong>Agent 工作台</strong>
        </Link>
        <nav aria-label="主导航">
          {navigation.map((item) => (
            <button
              aria-current={activePage === item.id ? "page" : undefined}
              key={item.id}
              onClick={() => onNavigate(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>
        <p className="sidebar-foot">本地 Agent 工作台</p>
      </aside>
      <header className="topbar">{header}</header>
      <main>{children}</main>
    </div>
  );
}
