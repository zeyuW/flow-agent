import { z } from "zod";

/** 控制台用于呈现 Trace 状态的视觉状态。 */
export type RuntimeStatus = "healthy" | "degraded" | "stopped" | "failed" | "unknown";

/** flow-agent-admin-api 当前实际提供的 Trace 列表项。 */
export const traceStatusSchema = z.string().min(1);

export const traceEventSchema = z.object({
  type: z.string(),
  at: z.string(),
  status: z.string(),
  summary: z.string(),
  error: z.string().nullable().optional(),
  trace_id: z.string().optional()
});
export type TraceEvent = z.infer<typeof traceEventSchema>;

export const traceSummarySchema = z.object({
  id: z.string(),
  channel: z.string(),
  status: traceStatusSchema,
  started_at: z.string().nullable(),
  duration_ms: z.number().nonnegative()
});
export type TraceSummary = z.infer<typeof traceSummarySchema>;

export const traceDetailSchema = traceSummarySchema.extend({
  finished_at: z.string().nullable(),
  error: z.string().nullable(),
  events: z.array(traceEventSchema)
});
export type TraceDetail = z.infer<typeof traceDetailSchema>;

export const sessionSummarySchema = z.object({
  id: z.string(),
  channel: z.string(),
  external_conversation_id: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  message_count: z.number().int().nonnegative(),
  preview: z.string().nullable()
});
export type SessionSummary = z.infer<typeof sessionSummarySchema>;

export const sessionMessageSchema = z.object({
  role: z.enum(["user", "assistant"]),
  content: z.string(),
  timestamp: z.string(),
  tool_chain: z.array(z.string())
});
export type SessionMessage = z.infer<typeof sessionMessageSchema>;

export const sessionDetailSchema = sessionSummarySchema.extend({
  messages: z.array(sessionMessageSchema)
});
export type SessionDetail = z.infer<typeof sessionDetailSchema>;

export const scheduleSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  trigger: z.string(),
  task_type: z.string(),
  message: z.string(),
  channel: z.string(),
  session_id: z.string(),
  timezone: z.string(),
  next_run_at: z.string(),
  interval_seconds: z.number().int().nullable(),
  daily_time: z.string().nullable(),
  enabled: z.boolean(),
  run_count: z.number().int().nonnegative(),
  created_at: z.string().nullable(),
  last_error: z.string().nullable()
});
export type ScheduleSummary = z.infer<typeof scheduleSummarySchema>;

export const skillCapabilitySchema = z.object({
  name: z.string(),
  description: z.string(),
  source: z.enum(["project", "installed"]),
  status: z.enum(["available", "conflict"]),
  reason: z.string().nullable()
});

export const connectorCapabilitySchema = z.object({
  name: z.string(),
  connected: z.boolean(),
  tools: z.array(z.string())
});

export const capabilitySnapshotSchema = z.object({
  skills: z.array(skillCapabilitySchema),
  connectors: z.array(connectorCapabilitySchema)
});
export type CapabilitySnapshot = z.infer<typeof capabilitySnapshotSchema>;
