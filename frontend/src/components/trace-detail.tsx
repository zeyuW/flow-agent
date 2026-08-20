import type { TraceDetail } from "@/lib/api/schemas";

function formatTime(value: string | null) {
  if (!value) return "尚未开始";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export function TraceDetailPanel({ trace }: { trace: TraceDetail | undefined }) {
  if (!trace) return <><h2>Trace 详情</h2><p className="muted">选择一条 Trace 查看处理阶段。</p></>;

  return (
    <>
      <h2>Trace 详情</h2>
      <p className="muted">{trace.id}</p>
      <div className="detail-item"><span>开始时间</span><time>{formatTime(trace.started_at)}</time></div>
      <div className="detail-item"><span>耗时</span><strong>{trace.duration_ms} ms</strong></div>
      {trace.error && <p className="trace-error" role="alert">{trace.error}</p>}
      <ol className="trace-timeline">
        {trace.events.map((event, index) => <li key={`${event.at}-${index}`}><time>{formatTime(event.at)}</time><strong>{event.summary}</strong><span>{event.type}</span></li>)}
      </ol>
    </>
  );
}
