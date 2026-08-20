import Link from "next/link";
import type { ReactNode } from "react";

const navigation = [
  "概览",
  "会话与回合",
  "投递与事件",
  "自动化与主动策略",
  "记忆",
  "渠道",
  "扩展",
  "审计日志",
  "设置与权限"
];

export function WorkbenchShell({
  children,
  details,
  header
}: {
  children: ReactNode;
  details: ReactNode;
  header: ReactNode;
}) {
  return (
    <div className="workbench">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span>FLOW</span>
          <strong>Agent 控制台</strong>
        </Link>
        <nav aria-label="主导航">
          {navigation.map((item, index) => (
            <a aria-current={index === 0 ? "page" : undefined} href={index === 0 ? "/" : "#"} key={item}>
              {item}
            </a>
          ))}
        </nav>
        <p className="sidebar-foot">观察工作区 · 管理员</p>
      </aside>
      <header className="topbar">{header}</header>
      <main>{children}</main>
      <aside className="details-panel">{details}</aside>
    </div>
  );
}
