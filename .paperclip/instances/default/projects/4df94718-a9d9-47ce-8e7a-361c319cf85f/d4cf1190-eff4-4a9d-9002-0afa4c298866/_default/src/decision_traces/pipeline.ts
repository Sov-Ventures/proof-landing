import type { DecisionTraceWriteEvent, ExtractedDecisionTrace, TradeLifecycleEdgeType, TraceEdgeType } from "./types";
import type { DecisionExtractor } from "./extractor";
import type { OutcomeEdgeEmitter } from "./outcome_edge_emitter";
import { validateRationalePayload, applyGuardrailResult } from "./rationale_guardrails";

export interface DecisionTraceRepository {
  insert(input: {
    companyId: string;
    issueId?: string;
    projectId?: string;
    goalId?: string;
    sourceKind: string;
    sourceId: string;
    sourceRunId?: string;
    actorAgentId?: string;
    actorUserId?: string;
    alternatives?: string[];
    authority?: {
      type: "agent" | "user" | "role" | "board" | "unknown";
      reference?: string;
      label?: string;
    };
    extracted: ExtractedDecisionTrace;
  }): Promise<void>;

  insertLifecycleEdge?(input: {
    companyId: string;
    issueId?: string;
    projectId?: string;
    goalId?: string;
    edgeType: TradeLifecycleEdgeType;
    fromSourceId: string;
    toSourceId: string;
    fromTraceType?: string;
    toTraceType?: string;
    metadata?: Record<string, unknown>;
  }): Promise<void>;

  insertTraceEdge?(input: {
    companyId: string;
    fromTraceId: string;
    toTraceId: string;
    edgeType: TraceEdgeType;
    inferredBy: string;
    confidence?: number;
    metadata?: Record<string, unknown>;
  }): Promise<void>;
}

export class DecisionTracePipeline {
  constructor(
    private readonly extractor: DecisionExtractor,
    private readonly repository: DecisionTraceRepository,
    private readonly outcomeEmitter?: OutcomeEdgeEmitter,
  ) {}

  async handleWriteEvent(event: DecisionTraceWriteEvent): Promise<boolean> {
    const extracted = await this.extractor.extract(event);
    if (!extracted) return false;

    // ZER-1238: validate rationale payload quality and annotate trace.
    const guardrailResult = validateRationalePayload(event.sourceKind, extracted);
    applyGuardrailResult(extracted, guardrailResult);

    await this.repository.insert({
      companyId: event.companyId,
      issueId: event.issueId,
      projectId: event.projectId,
      goalId: event.goalId,
      sourceKind: event.sourceKind,
      sourceId: event.sourceId,
      sourceRunId: event.sourceRunId,
      actorAgentId: event.actorAgentId,
      actorUserId: event.actorUserId,
      alternatives: extracted.alternatives,
      authority: extracted.authority,
      extracted,
    });

    if (event.metadata?.lifecycleEdge && this.repository.insertLifecycleEdge) {
      await this.repository.insertLifecycleEdge({
        companyId: event.companyId,
        issueId: event.issueId,
        projectId: event.projectId,
        goalId: event.goalId,
        edgeType: event.metadata.lifecycleEdge.edgeType,
        fromSourceId: event.metadata.lifecycleEdge.fromSourceId,
        toSourceId: event.sourceId,
        fromTraceType: undefined,
        toTraceType: extracted.traceType,
        metadata: {
          sourceKind: event.sourceKind,
          strategyKey: event.metadata.strategyKey,
          symbol: event.metadata.symbol,
        },
      });
    }

    if (this.outcomeEmitter) {
      await this.emitOutcomeEdges(event, extracted);
    }

    return true;
  }

  private async emitOutcomeEdges(
    event: DecisionTraceWriteEvent,
    extracted: ExtractedDecisionTrace,
  ): Promise<void> {
    if (!this.outcomeEmitter) return;

    if (event.sourceKind === "approval_resolved" && event.metadata?.approvalOutcome) {
      await this.outcomeEmitter.emitReviewOutcome({
        companyId: event.companyId,
        approvalSourceId: event.sourceId,
        outcome: event.metadata.approvalOutcome as "approved" | "rejected" | "changes_requested",
        resolvedAt: event.occurredAt,
      });
    }

    if (
      event.sourceKind === "trade_exit" &&
      event.metadata?.lifecycleEdge?.edgeType === "entry_to_exit"
    ) {
      const pnlBps =
        typeof event.metadata.pnlBps === "number"
          ? event.metadata.pnlBps
          : typeof extracted.contextSnapshot?.pnlBps === "number"
            ? extracted.contextSnapshot.pnlBps
            : undefined;

      if (pnlBps !== undefined) {
        await this.outcomeEmitter.emitTradeOutcome({
          companyId: event.companyId,
          exitSourceId: event.sourceId,
          entrySourceId: event.metadata.lifecycleEdge.fromSourceId,
          pnlBps,
          resolvedAt: event.occurredAt,
          strategyKey: event.metadata.strategyKey as string | undefined,
          symbol: event.metadata.symbol as string | undefined,
          regime: event.metadata.regime as string | undefined,
        });
      }
    }
  }
}
