import type { DecisionTraceHooks } from "./event_hooks";
import type { CodeArtifact, DecisionTraceEventMetadata } from "./types";

export interface TradeInstrumentationBaseContext {
  companyId: string;
  issueId?: string;
  projectId?: string;
  goalId?: string;
  actorAgentId?: string;
  sourceRunId?: string;
  strategyKey: string;
  symbol?: string;
  codeArtifact?: CodeArtifact;
}

export interface TradeSignalInput {
  sourceId: string;
  occurredAt: string;
  body: string;
  metadata?: DecisionTraceEventMetadata;
}

export interface TradeEntryInput extends TradeSignalInput {
  signalSourceId?: string;
  positionId?: string;
  orderId?: string;
}

export interface TradeExitInput extends TradeSignalInput {
  entrySourceId?: string;
  positionId?: string;
  orderId?: string;
}

export interface PositionAdjustmentInput extends TradeSignalInput {
  priorEventSourceId?: string;
  positionId?: string;
  orderId?: string;
}

export class TradeExecutionInstrumentor {
  constructor(
    private readonly hooks: DecisionTraceHooks,
    private readonly base: TradeInstrumentationBaseContext,
  ) {}

  async emitSignal(input: TradeSignalInput): Promise<boolean> {
    return this.hooks.onTradeSignal(this.toEvent(input));
  }

  async emitEntry(input: TradeEntryInput): Promise<boolean> {
    return this.hooks.onTradeEntry(this.toEvent(input, input), input.signalSourceId);
  }

  async emitExit(input: TradeExitInput): Promise<boolean> {
    return this.hooks.onTradeExit(this.toEvent(input, input), input.entrySourceId);
  }

  async emitPositionAdjustment(input: PositionAdjustmentInput): Promise<boolean> {
    return this.hooks.onPositionAdjustment(this.toEvent(input, input), input.priorEventSourceId);
  }

  async emitSkip(input: TradeSignalInput): Promise<boolean> {
    return this.hooks.onTradeSkip(this.toEvent(input));
  }

  private toEvent(input: TradeSignalInput, withOrderContext?: { positionId?: string; orderId?: string }) {
    return {
      companyId: this.base.companyId,
      issueId: this.base.issueId,
      projectId: this.base.projectId,
      goalId: this.base.goalId,
      sourceId: input.sourceId,
      sourceRunId: this.base.sourceRunId,
      actorAgentId: this.base.actorAgentId,
      occurredAt: input.occurredAt,
      body: input.body,
      metadata: {
        ...(input.metadata ?? {}),
        strategyKey: this.base.strategyKey,
        symbol: input.metadata?.symbol || this.base.symbol,
        positionId: withOrderContext?.positionId ?? input.metadata?.positionId,
        orderId: withOrderContext?.orderId ?? input.metadata?.orderId,
        ...(input.metadata?.codeArtifact || this.base.codeArtifact
          ? { codeArtifact: input.metadata?.codeArtifact ?? this.base.codeArtifact }
          : {}),
      },
    };
  }
}
