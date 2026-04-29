export type DecisionTraceEventKind =
  | "issue_created"
  | "issue_comment_created"
  | "issue_status_changed"
  | "issue_reassigned"
  | "approval_requested"
  | "approval_resolved"
  | "trade_signal"
  | "trade_entry"
  | "trade_exit"
  | "position_adjustment"
  | "trade_skip";

export type TradeTraceType =
  | "trade_signal"
  | "trade_entry"
  | "trade_exit"
  | "position_adjustment"
  | "trade_skip";

export type TradeLifecycleEdgeType = "signal_to_entry" | "entry_to_exit" | "config_change";

export interface DecisionTraceLifecycleEdgeHint {
  edgeType: TradeLifecycleEdgeType;
  fromSourceId: string;
}

export interface CodeArtifact {
  repo?: string;
  ref?: string;
  filePath?: string;
}

export interface DecisionTraceEventMetadata {
  lifecycleEdge?: DecisionTraceLifecycleEdgeHint;
  codeArtifact?: CodeArtifact;
  strategyKey?: string;
  symbol?: string;
  positionId?: string;
  orderId?: string;
  [key: string]: unknown;
}

export interface DecisionTraceWriteEvent {
  companyId: string;
  issueId?: string;
  projectId?: string;
  goalId?: string;
  sourceKind: DecisionTraceEventKind;
  sourceId: string;
  sourceRunId?: string;
  actorAgentId?: string;
  actorUserId?: string;
  occurredAt: string;
  body: string;
  metadata?: DecisionTraceEventMetadata;
}

export interface ExtractedDecisionTrace {
  traceType: string;
  summary: string;
  reasoning?: string;
  alternatives?: string[];
  authority?: {
    type: "agent" | "user" | "role" | "board" | "unknown";
    reference?: string;
    label?: string;
  };
  outcomeSignal?: string;
  outcomeNote?: string;
  tags?: string[];
  confidence?: number;
  contextSnapshot?: Record<string, unknown>;
}

export type TraceEdgeType =
  | "caused_by"
  | "supersedes"
  | "informed_by"
  | "contradicts"
  | "escalated_to"
  | "resolved_by"
  | "signal_to_entry"
  | "entry_to_exit"
  | "config_change"
  | "results_in";

export interface DecisionTraceRecord {
  id: string;
  companyId: string;
  issueId?: string;
  projectId?: string;
  goalId?: string;
  actorAgentId?: string;
  actorUserId?: string;
  sourceKind: string;
  traceType: string;
  tags?: string[];
  outcomeSignal?: string;
  contextSnapshot?: Record<string, unknown>;
  createdAt: string;
}

export interface TraceEdgeInsert {
  fromTraceId: string;
  toTraceId: string;
  edgeType: TraceEdgeType;
  inferredBy: string;
  confidence?: number;
  metadata?: Record<string, unknown>;
}
