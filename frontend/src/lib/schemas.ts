import { z } from "zod";

export const roleSchema = z.enum(["ADMIN", "MANAGER", "VIEWER"]);
export const decisionSchema = z.enum(["ALLOW", "BLOCK", "REQUIRE_APPROVAL"]);
export const actionStatusSchema = z.enum(["ALLOWED", "BLOCKED", "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXPIRED"]);
export const approvalStatusSchema = z.enum(["PENDING", "APPROVED", "REJECTED", "EXPIRED"]);
export const riskSchema = z.enum(["LOW", "MEDIUM", "HIGH", "CRITICAL"]);
export const policyTypeSchema = z.enum(["RULE", "RATE_LIMIT", "UNKNOWN_TOOL", "REPEATED_ACTION"]);
export const operatorSchema = z.enum(["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "contains", "not_contains", "startswith", "regex"]);

export const pageOf = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), total: z.number(), page: z.number(), page_size: z.number(), pages: z.number() });

export const userSchema = z.object({ id: z.string(), email: z.string(), full_name: z.string(), is_active: z.boolean(), created_at: z.string() });
export const orgSchema = z.object({ id: z.string(), name: z.string(), slug: z.string() });
export const meSchema = z.object({ user: userSchema, organization: orgSchema, role: roleSchema });

export const agentSchema = z.object({
  id: z.string(), slug: z.string(), name: z.string(), description: z.string().nullable(),
  status: z.enum(["ACTIVE", "DISABLED"]), created_at: z.string(), updated_at: z.string(),
});
export const toolSchema = z.object({
  id: z.string(), name: z.string(), description: z.string().nullable(), risk_level: riskSchema,
  is_active: z.boolean(), created_at: z.string(), updated_at: z.string(),
});
export const apiKeySchema = z.object({
  id: z.string(), agent_id: z.string(), name: z.string(), prefix: z.string(), created_at: z.string(),
  expires_at: z.string().nullable(), revoked_at: z.string().nullable(), last_used_at: z.string().nullable(),
});
export const apiKeyListItemSchema = apiKeySchema.extend({ agent_slug: z.string(), agent_name: z.string() });
export const apiKeyCreatedSchema = apiKeySchema.extend({ key: z.string() });

export const ruleSchema = z.object({ id: z.string().optional(), position: z.number().optional(), field: z.string(), operator: operatorSchema, value: z.unknown() });
export const policySchema = z.object({
  id: z.string(), name: z.string(), description: z.string().nullable(), policy_type: policyTypeSchema,
  effect: decisionSchema, priority: z.number(), is_active: z.boolean(), reason_code: z.string(),
  message: z.string().nullable(), config: z.record(z.unknown()), rules: z.array(ruleSchema),
  created_at: z.string(), updated_at: z.string(),
});

export const approvalSchema = z.object({
  id: z.string(), action_request_id: z.string(), action_id: z.string(), agent_slug: z.string(), tool: z.string(),
  environment: z.string(), estimated_cost: z.coerce.number(), arguments: z.record(z.unknown()),
  reason: z.string().nullable(), message: z.string().nullable(), status: approvalStatusSchema, expires_at: z.string(),
  policy_id: z.string().nullable().optional(), policy_name: z.string().nullable().optional(),
  decided_by_email: z.string().nullable().optional(), decided_at: z.string().nullable().optional(),
  decision_reason: z.string().nullable().optional(), created_at: z.string(),
});

export const actionSchema = z.object({
  id: z.string(), action_id: z.string(), agent_id: z.string(), agent_slug: z.string(), tool: z.string(),
  environment: z.string(), arguments: z.record(z.unknown()), estimated_cost: z.coerce.number(),
  reason: z.string().nullable(), decision: decisionSchema, status: actionStatusSchema,
  reason_code: z.string().nullable(), outcome: z.enum(["SUCCEEDED", "FAILED"]).nullable(),
  secrets_redacted: z.number(), policy_name: z.string().nullable().optional(), message: z.string().nullable().optional(),
  approval_id: z.string().nullable().optional(), created_at: z.string(),
});
export const actionDetailSchema = actionSchema.extend({ trace: z.array(z.record(z.unknown())), latency_ms: z.number().nullable().optional() });

export const auditSchema = z.object({
  id: z.string(), seq: z.number(), actor_type: z.enum(["USER", "AGENT", "SYSTEM"]), actor_label: z.string().nullable(),
  event_type: z.string(), entity_type: z.string(), entity_id: z.string().nullable(), details: z.record(z.unknown()),
  prev_hash: z.string(), entry_hash: z.string(), created_at: z.string(),
});
export const auditVerifySchema = z.object({ valid: z.boolean(), checked: z.number(), first_invalid_seq: z.number().nullable() });

export const memberSchema = z.object({
  user_id: z.string(), email: z.string(), full_name: z.string(), role: roleSchema, is_active: z.boolean(), created_at: z.string(),
});

const point = z.object({ bucket: z.string(), total: z.number(), allowed: z.number(), blocked: z.number(), approvals: z.number() });
export const analyticsSchema = z.object({
  days: z.number(),
  totals: z.object({
    total: z.number(), allowed: z.number(), blocked: z.number(), approvals_required: z.number(), secrets_redacted: z.number(),
    block_rate: z.number(), pending_approvals: z.number(), rate_limited: z.number(),
  }),
  approvals: z.record(z.number()),
  timeseries: z.array(point),
  agent_activity: z.array(z.object({ agent: z.string(), name: z.string(), total: z.number(), allowed: z.number(), blocked: z.number(), approvals: z.number() })),
  top_tools: z.array(z.object({ tool: z.string(), total: z.number(), blocked: z.number() })),
  block_reasons: z.array(z.object({ reason_code: z.string(), count: z.number() })),
  cached: z.boolean().optional(),
});

export const simulateSchema = z.object({
  decision: decisionSchema, reason_code: z.string(), message: z.string().nullable(), policy_name: z.string().nullable(),
  tool_known: z.boolean(), tool_permitted: z.boolean(), trace: z.array(z.record(z.unknown())), note: z.string(),
});

export const loginSchema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(1, "Enter your password") });
export const registerSchema = z.object({
  full_name: z.string().min(1, "Enter your name").max(120),
  organization_name: z.string().min(2, "At least 2 characters").max(120),
  email: z.string().email("Enter a valid email"),
  password: z.string().min(10, "Use at least 10 characters").max(128),
});
export const agentFormSchema = z.object({
  slug: z.string().regex(/^[a-z0-9][a-z0-9_-]{0,78}[a-z0-9]$/, "Lowercase letters, digits, - and _ (2–80 chars)"),
  name: z.string().min(1, "Enter a name").max(120),
  description: z.string().max(2000).optional(),
});
export const toolFormSchema = z.object({
  name: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/, "Letters, digits, . _ : - only"),
  description: z.string().max(2000).optional(),
  risk_level: riskSchema,
});
export const apiKeyFormSchema = z.object({
  name: z.string().min(1, "Enter a name").max(120),
  expires_in_days: z.coerce.number().int().min(1).max(3650).optional(),
});
