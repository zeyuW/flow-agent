import type { TraceEvent } from "@/lib/api/schemas";

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export function EventTimeline({
  events,
  onSelectTrace
}: {
  events: TraceEvent[];
  onSelectTrace: (traceId: string) => void;
}) {
  if (events.length === 0) return <p className="empty-state">暂无近期事件。</p>;

  return (
    <ol className="event-timeline">
      {events.map((event, index) => {
        const content = <><time>{formatTime(event.at)}</time><strong>{event.summary}</strong><span>{event.type}</span></>;
        return (
          <li key={`${event.at}-${index}`}>
            {event.trace_id ? <button onClick={() => onSelectTrace(event.trace_id ?? "")} type="button">{content}</button> : <div>{content}</div>}
          </li>
        );
      })}
    </ol>
  );
}
