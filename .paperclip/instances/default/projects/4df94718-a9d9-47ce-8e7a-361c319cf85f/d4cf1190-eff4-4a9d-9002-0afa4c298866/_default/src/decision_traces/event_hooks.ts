import type { DecisionTracePipeline } from "./pipeline";
import type {
  DecisionTraceEventMetadata,
  DecisionTraceLifecycleEdgeHint,
  DecisionTraceWriteEvent,
} from "./types";

// Wire these handlers into the Paperclip write path where comments/approvals/status
// transitions/reassignments are persisted.
export class DecisionTraceHooks {
  constructor(private readonly pipeline: DecisionTracePipeline) {}

  async onCommentCreated(event: Omit<DecisionTraceWriteEvent, "sourceKind">): Promise<boolean> {
    return this.pipeline.handleWriteEvent({ ...event, sourceKind: "issue_comment_created" });
  }

  async onApprovalResolved(event: Omit<DecisionTraceWriteEvent, "sourceKind">): Promise<boolean> {
    return this.pipeline.handleWriteEvent({ ...event, sourceKind: "approval_resolved" });
  }

  async onIssueStatusChanged(event: Omit<DecisionTraceWriteEvent, "sourceKind">): Promise<boolean> {
    return this.pipeline.handleWriteEvent({ ...event, sourceKind: "issue_status_changed" });
  }

  async onIssueReassigned(event: Omit<DecisionTraceWriteEvent, "sourceKind">): Promise<boolean> {
    return this.pipeline.handleWriteEvent({ ...event, sourceKind: "issue_reassigned" });
  }

  async onTradeSignal(event: Omit<DecisionTraceWriteEvent, "sourceKind">): Promise<boolean> {
    return this.pipeline.handleWriteEvent({ ...event, sourceKind: "trade_signal" });
  }

  async onTradeEntry(
    event: Omit<DecisionTraceWriteEvent, "sourceKind">,
    signalSourceId?: string,
  ): Promise<boolean> {
    return this.pipeline.handleWriteEvent({
      ...event,
      metadata: mergeLifecycleEdge(event.metadata, signalSourceId, "signal_to_entry"),
      sourceKind: "trade_entry",
    });
  }

  async onTradeExit(
    event: Omit<DecisionTraceWriteEvent, "sourceKind">,
    entrySourceId?: string,
  ): Promise<boolean> {
    return this.pipeline.handleWriteEvent({
      ...event,
      metadata: mergeLifecycleEdge(event.metadata, entrySourceId, "entry_to_exit"),
      sourceKind: "trade_exit",
    });
  }

  async onPositionAdjustment(
    event: Omit<DecisionTraceWriteEvent, "sourceKind">,
    priorEventSourceId?: string,
  ): Promise<boolean> {
    return this.pipeline.handleWriteEvent({
      ...event,
      metadata: mergeLifecycleEdge(event.metadata, priorEventSourceId, "config_change"),
      sourceKind: "position_adjustment",
    });
  }

  async onTradeSkip(event: Omit<DecisionTraceWriteEvent, "sourceKind">): Promise<boolean> {
    return this.pipeline.handleWriteEvent({ ...event, sourceKind: "trade_skip" });
  }
}

function mergeLifecycleEdge(
  metadata: DecisionTraceEventMetadata | undefined,
  fromSourceId: string | undefined,
  edgeType: DecisionTraceLifecycleEdgeHint["edgeType"],
): DecisionTraceEventMetadata | undefined {
  if (!fromSourceId) return metadata;
  return {
    ...(metadata ?? {}),
    lifecycleEdge: {
      edgeType,
      fromSourceId,
    },
  };
}
