import { z } from "zod";

import {
  sessionDetailSchema,
  sessionSummarySchema,
  traceDetailSchema,
  traceEventSchema,
  traceSummarySchema,
  type SessionDetail,
  type SessionSummary,
  type TraceDetail,
  type TraceEvent,
  type TraceSummary
} from "./schemas";

export class AdminApiError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message);
    this.name = "AdminApiError";
  }
}

async function getJson<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: { Accept: "application/json" },
      cache: "no-store"
    });
  } catch {
    throw new AdminApiError("无法连接管理 API");
  }

  if (!response.ok) {
    throw new AdminApiError(`管理 API 返回 ${response.status}`, response.status);
  }

  let json: unknown;
  try {
    json = await response.json();
  } catch {
    throw new AdminApiError("管理 API 返回了无效 JSON", response.status);
  }
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    throw new AdminApiError("管理 API 返回了无效数据");
  }
  return parsed.data;
}

/** 读取管理 API 的事件快照；该接口不是 SSE。 */
export function getEvents(): Promise<TraceEvent[]> {
  return getJson("/api/events", z.array(traceEventSchema));
}

export function getTraces(): Promise<TraceSummary[]> {
  return getJson("/api/traces", z.array(traceSummarySchema));
}

export function getTrace(traceId: string): Promise<TraceDetail> {
  return getJson(`/api/traces/${encodeURIComponent(traceId)}`, traceDetailSchema);
}

export function getSessions(
  startDate: string,
  endDate: string
): Promise<SessionSummary[]> {
  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    limit: "50"
  });
  return getJson(`/api/sessions?${params}`, z.array(sessionSummarySchema));
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return getJson(
    `/api/sessions/${encodeURIComponent(sessionId)}`,
    sessionDetailSchema
  );
}
