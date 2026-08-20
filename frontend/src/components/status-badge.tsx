import type { RuntimeStatus } from "@/lib/api/schemas";

const statusPresentation: Record<RuntimeStatus, { label: string; tone: string }> = {
  healthy: { label: "运行正常", tone: "success" },
  degraded: { label: "性能降级", tone: "warning" },
  stopped: { label: "已停止", tone: "neutral" },
  failed: { label: "运行失败", tone: "danger" },
  unknown: { label: "状态未知", tone: "unknown" }
};

export function StatusBadge({ status }: { status: RuntimeStatus }) {
  const presentation = statusPresentation[status];

  return <span className={`status-badge status-${presentation.tone}`}>{presentation.label}</span>;
}
