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
