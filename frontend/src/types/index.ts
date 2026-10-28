import type { z } from "zod";
import type * as s from "@/lib/schemas";

export type Role = z.infer<typeof s.roleSchema>;
export type Decision = z.infer<typeof s.decisionSchema>;
export type ActionStatus = z.infer<typeof s.actionStatusSchema>;
export type ApprovalStatus = z.infer<typeof s.approvalStatusSchema>;
export type RiskLevel = z.infer<typeof s.riskSchema>;
export type PolicyType = z.infer<typeof s.policyTypeSchema>;
export type Operator = z.infer<typeof s.operatorSchema>;
export type Me = z.infer<typeof s.meSchema>;
export type Agent = z.infer<typeof s.agentSchema>;
export type Tool = z.infer<typeof s.toolSchema>;
export type ApiKeyItem = z.infer<typeof s.apiKeyListItemSchema>;
export type ApiKeyCreated = z.infer<typeof s.apiKeyCreatedSchema>;
export type Policy = z.infer<typeof s.policySchema>;
export type Rule = z.infer<typeof s.ruleSchema>;
export type Approval = z.infer<typeof s.approvalSchema>;
export type Action = z.infer<typeof s.actionSchema>;
export type ActionDetail = z.infer<typeof s.actionDetailSchema>;
export type AuditLog = z.infer<typeof s.auditSchema>;
export type Member = z.infer<typeof s.memberSchema>;
export type Analytics = z.infer<typeof s.analyticsSchema>;
export type SimulationResult = z.infer<typeof s.simulateSchema>;
export interface Page<T> { items: T[]; total: number; page: number; page_size: number; pages: number }
