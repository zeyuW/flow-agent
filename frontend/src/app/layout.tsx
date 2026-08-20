import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Providers } from "./providers";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "Flow Agent 控制台",
  description: "Flow Agent 管理与运行观测工作台"
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
