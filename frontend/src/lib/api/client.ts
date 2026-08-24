import { z } from "zod";

import {
  capabilitySnapshotSchema,
  mcpServerSchema,
  scheduleSummarySchema,
  sessionDetailSchema,
  sessionSummarySchema,
  traceDetailSchema,
  traceEventSchema,
  traceSummarySchema,
  type SessionDetail,
  type SessionSummary,
  type ScheduleSummary,
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
  return requestJson(path, schema);
}

async function requestJson<T>(
  path: string,
  schema: z.ZodType<T>,
  method = "GET",
  body?: string
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: {
        Accept: "application/json",
        ...(body ? { "Content-Type": "application/json" } : {})
      },
      cache: "no-store",
      method,
      body
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

export function getSession(
  sessionId: string,
  startDate: string,
  endDate: string
): Promise<SessionDetail> {
  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate
  });
  return getJson(
    `/api/sessions/${encodeURIComponent(sessionId)}?${params}`,
    sessionDetailSchema
  );
}

export function getSchedules(): Promise<ScheduleSummary[]> {
  return getJson("/api/schedules", z.array(scheduleSummarySchema));
}

export function getCapabilities() {
  return getJson("/api/capabilities", capabilitySnapshotSchema);
}

const mcpInputSchema = z.object({
  command: z.string().default(""),
  url: z.string().nullable().optional(),
  description: z.string().optional(),
  args: z.array(z.string()).optional(),
  env: z.record(z.string()).optional(),
  headers: z.record(z.string()).optional(),
  cwd: z.string().nullable().optional(),
  enabled: z.boolean().optional()
});
export type McpServerInput = z.input<typeof mcpInputSchema>;

export function getMcpServers() {
  return getJson("/api/mcp/servers", z.array(mcpServerSchema));
}

export function saveMcpServer(name: string, input: McpServerInput) {
  return requestJson(
    `/api/mcp/servers/${encodeURIComponent(name)}`,
    mcpServerSchema,
    "PUT",
    JSON.stringify(input)
  );
}

export async function setMcpServerEnabled(name: string, enabled: boolean): Promise<void> {
  await requestJson(
    `/api/mcp/servers/${encodeURIComponent(name)}/enabled`,
    z.object({ enabled: z.boolean() }),
    "POST",
    JSON.stringify({ enabled })
  );
}

export async function removeMcpServer(name: string): Promise<void> {
  await requestJson(
    `/api/mcp/servers/${encodeURIComponent(name)}`,
    z.object({ removed: z.literal(true) }),
    "DELETE"
  );
}

const skillListSchema = z.object({ skills: z.array(z.object({ name: z.string() })) });

export async function scanSkills(repositoryUrl: string): Promise<{ name: string }[]> {
  const response = await requestJson(
    "/api/skills/scan",
    skillListSchema,
    "POST",
    JSON.stringify({ repository_url: repositoryUrl })
  );
  return response.skills;
}

export async function installSkill(
  repositoryUrl: string,
  names: string[]
): Promise<{ name: string }[]> {
  const response = await requestJson(
    "/api/skills/install",
    skillListSchema,
    "POST",
    JSON.stringify({ repository_url: repositoryUrl, names })
  );
  return response.skills;
}

export async function uninstallSkill(name: string): Promise<void> {
  await requestJson(
    `/api/skills/${encodeURIComponent(name)}`,
    z.object({ removed: z.literal(true) }),
    "DELETE"
  );
}

export async function cancelSchedule(taskId: string): Promise<void> {
  await requestJson(
    `/api/schedules/${encodeURIComponent(taskId)}/cancel`,
    z.object({ cancelled: z.literal(true) }),
    "POST"
  );
}

export type CreateScheduleInput = {
  target_task_id: string;
  name: string;
  trigger: "after" | "at" | "daily" | "every";
  when: string;
  task_type: "reminder" | "agent";
  message: string;
};

export function createSchedule(
  input: CreateScheduleInput
): Promise<ScheduleSummary> {
  return requestJson(
    "/api/schedules",
    scheduleSummarySchema,
    "POST",
    JSON.stringify(input)
  );
}

export async function resumeSchedule(taskId: string): Promise<void> {
  await requestJson(
    `/api/schedules/${encodeURIComponent(taskId)}/resume`,
    z.object({ resumed: z.literal(true) }),
    "POST"
  );
}
