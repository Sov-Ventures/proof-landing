import type { DecisionTraceHooks } from "./event_hooks";
import type { CodeArtifact, DecisionTraceEventMetadata } from "./types";

export interface PaperclipIssueEventBase {
  companyId: string;
  issueId: string;
  projectId?: string;
  goalId?: string;
  runId?: string;
  actorAgentId?: string;
  actorUserId?: string;
  occurredAt: string;
  codeArtifact?: CodeArtifact;
}

export interface PaperclipIssueCreatedEvent extends PaperclipIssueEventBase {
  title: string;
  description?: string;
  parentIssueId?: string;
  assigneeAgentId?: string;
  assigneeUserId?: string;
}

export interface PaperclipIssueCommentCreatedEvent extends PaperclipIssueEventBase {
  commentId: string;
  body: string;
}

export interface PaperclipIssueStatusChangedEvent extends PaperclipIssueEventBase {
  fromStatus: string;
  toStatus: string;
  note?: string;
}

export interface PaperclipIssueReassignedEvent extends PaperclipIssueEventBase {
  fromAssigneeAgentId?: string;
  fromAssigneeUserId?: string;
  toAssigneeAgentId?: string;
  toAssigneeUserId?: string;
  note?: string;
}

export interface PaperclipApprovalRequestedEvent extends PaperclipIssueEventBase {
  approvalId: string;
  approvalType?: string;
  title: string;
  summary?: string;
}

export interface PaperclipApprovalResolvedEvent extends PaperclipIssueEventBase {
  approvalId: string;
  outcome: "approved" | "rejected" | "changes_requested";
  approvalType?: string;
  summary?: string;
}

export class PaperclipDecisionTraceBridge {
  constructor(private readonly hooks: DecisionTraceHooks) {}

  async onIssueCreated(event: PaperclipIssueCreatedEvent): Promise<boolean> {
    return this.hooks.onIssueCreated({
      companyId: event.companyId,
      issueId: event.issueId,
      projectId: event.projectId,
      goalId: event.goalId,
      sourceId: event.issueId,
      sourceRunId: event.runId,
      actorAgentId: event.actorAgentId,
      actorUserId: event.actorUserId,
      occurredAt: normalizeTimestamp(event.occurredAt),
      body: renderIssueCreatedBody(event),
      metadata: buildIssueMetadata("issue_created", {
        title: event.title,
        parentIssueId: event.parentIssueId,
        assigneeAgentId: event.assigneeAgentId,
        assigneeUserId: event.assigneeUserId,
      }, event.codeArtifact),
    });
  }

  async onApprovalRequested(event: PaperclipApprovalRequestedEvent): Promise<boolean> {
    return this.hooks.onApprovalRequested({
      companyId: event.companyId,
      issueId: event.issueId,
      projectId: event.projectId,
      goalId: event.goalId,
      sourceId: event.approvalId,
      sourceRunId: event.runId,
      actorAgentId: event.actorAgentId,
      actorUserId: event.actorUserId,
      occurredAt: normalizeTimestamp(event.occurredAt),
      body: renderApprovalRequestedBody(event),
      metadata: buildIssueMetadata("approval_requested", {
        approvalId: event.approvalId,
        approvalType: event.approvalType,
      }, event.codeArtifact),
    });
  }

  async onIssueCommentCreated(event: PaperclipIssueCommentCreatedEvent): Promise<boolean> {
    return this.hooks.onCommentCreated({
      companyId: event.companyId,
      issueId: event.issueId,
      projectId: event.projectId,
      goalId: event.goalId,
      sourceId: event.commentId,
      sourceRunId: event.runId,
      actorAgentId: event.actorAgentId,
      actorUserId: event.actorUserId,
      occurredAt: normalizeTimestamp(event.occurredAt),
      body: event.body,
      metadata: buildIssueMetadata("issue_comment_created", undefined, event.codeArtifact),
    });
  }

  async onIssueStatusChanged(event: PaperclipIssueStatusChangedEvent): Promise<boolean> {
    return this.hooks.onIssueStatusChanged({
      companyId: event.companyId,
      issueId: event.issueId,
      projectId: event.projectId,
      goalId: event.goalId,
      sourceId: `${event.issueId}:status:${event.toStatus}:${normalizeTimestamp(event.occurredAt)}`,
      sourceRunId: event.runId,
      actorAgentId: event.actorAgentId,
      actorUserId: event.actorUserId,
      occurredAt: normalizeTimestamp(event.occurredAt),
      body: renderStatusBody(event),
      metadata: buildIssueMetadata("issue_status_changed", {
        fromStatus: event.fromStatus,
        toStatus: event.toStatus,
      }, event.codeArtifact),
    });
  }

  async onIssueReassigned(event: PaperclipIssueReassignedEvent): Promise<boolean> {
    return this.hooks.onIssueReassigned({
      companyId: event.companyId,
      issueId: event.issueId,
      projectId: event.projectId,
      goalId: event.goalId,
      sourceId: `${event.issueId}:reassign:${normalizeTimestamp(event.occurredAt)}`,
      sourceRunId: event.runId,
      actorAgentId: event.actorAgentId,
      actorUserId: event.actorUserId,
      occurredAt: normalizeTimestamp(event.occurredAt),
      body: renderReassignmentBody(event),
      metadata: buildIssueMetadata("issue_reassigned", {
        fromAssigneeAgentId: event.fromAssigneeAgentId,
        fromAssigneeUserId: event.fromAssigneeUserId,
        toAssigneeAgentId: event.toAssigneeAgentId,
        toAssigneeUserId: event.toAssigneeUserId,
      }, event.codeArtifact),
    });
  }

  async onApprovalResolved(event: PaperclipApprovalResolvedEvent): Promise<boolean> {
    return this.hooks.onApprovalResolved({
      companyId: event.companyId,
      issueId: event.issueId,
      projectId: event.projectId,
      goalId: event.goalId,
      sourceId: event.approvalId,
      sourceRunId: event.runId,
      actorAgentId: event.actorAgentId,
      actorUserId: event.actorUserId,
      occurredAt: normalizeTimestamp(event.occurredAt),
      body: renderApprovalBody(event),
      metadata: buildIssueMetadata("approval_resolved", {
        approvalId: event.approvalId,
        approvalType: event.approvalType,
        approvalOutcome: event.outcome,
      }, event.codeArtifact),
    });
  }
}

function renderIssueCreatedBody(event: PaperclipIssueCreatedEvent): string {
  const parts = [`issue created: ${event.title}`];
  if (event.description?.trim()) {
    parts.push(`description: ${event.description.trim().slice(0, 200)}`);
  }
  if (event.parentIssueId) {
    parts.push(`parent: ${event.parentIssueId}`);
  }
  return parts.join(". ");
}

function renderApprovalRequestedBody(event: PaperclipApprovalRequestedEvent): string {
  const parts = [`approval requested: ${event.title}`];
  if (event.approvalType?.trim()) {
    parts.push(`type: ${event.approvalType.trim()}`);
  }
  if (event.summary?.trim()) {
    parts.push(`summary: ${event.summary.trim()}`);
  }
  return parts.join(". ");
}

function renderStatusBody(event: PaperclipIssueStatusChangedEvent): string {
  const parts = [`issue status changed from ${event.fromStatus} to ${event.toStatus}`];
  if (event.note?.trim()) {
    parts.push(`note: ${event.note.trim()}`);
  }
  return parts.join(". ");
}

function renderReassignmentBody(event: PaperclipIssueReassignedEvent): string {
  const from = event.fromAssigneeAgentId ?? event.fromAssigneeUserId ?? "unassigned";
  const to = event.toAssigneeAgentId ?? event.toAssigneeUserId ?? "unassigned";
  const parts = [`issue reassigned from ${from} to ${to}`];
  if (event.note?.trim()) {
    parts.push(`note: ${event.note.trim()}`);
  }
  return parts.join(". ");
}

function renderApprovalBody(event: PaperclipApprovalResolvedEvent): string {
  const parts = [`approval ${event.approvalId} ${event.outcome}`];
  if (event.approvalType?.trim()) {
    parts.push(`type: ${event.approvalType.trim()}`);
  }
  if (event.summary?.trim()) {
    parts.push(`summary: ${event.summary.trim()}`);
  }
  return parts.join(". ");
}

function buildIssueMetadata(
  eventName: string,
  extra?: Record<string, unknown>,
  codeArtifact?: CodeArtifact,
): DecisionTraceEventMetadata {
  return {
    pipelineSource: "paperclip_write_path",
    eventName,
    ...(extra ?? {}),
    ...(codeArtifact ? { codeArtifact } : {}),
  };
}

function normalizeTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return new Date().toISOString();
  }
  return parsed.toISOString();
}
