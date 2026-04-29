/**
 * Outcome edge emitter (ZER-1240).
 *
 * Emits `results_in` edges from decision traces to outcome traces for:
 * 1. Review dispositions — approval_resolved events produce an outcome trace.
 * 2. Trade results — trade_exit events with PnL produce an outcome trace.
 *
 * Each emitter method resolves the source decision trace, creates an outcome
 * trace, and persists a `results_in` edge in the `trace_edges` table.
 */

import type { PgQueryable } from "./repository";
import type { TraceEdgeType } from "./types";
import { labelTradeOutcome, type OutcomeLabel } from "./outcome_attribution";

export interface OutcomeEdgeRow {
  companyId: string;
  fromTraceId: string;
  toTraceId: string;
  edgeType: TraceEdgeType;
  inferredBy: string;
  confidence: number;
  metadata: Record<string, unknown>;
}

export interface ReviewOutcomeInput {
  companyId: string;
  approvalSourceId: string;
  outcome: "approved" | "rejected" | "changes_requested";
  resolvedAt: string;
}

export interface IssueResolutionOutcomeInput {
  companyId: string;
  issueSourceId: string;
  toStatus: string;
  resolvedAt: string;
}

export interface TradeOutcomeInput {
  companyId: string;
  exitSourceId: string;
  entrySourceId: string;
  pnlBps: number;
  resolvedAt: string;
  strategyKey?: string;
  symbol?: string;
  regime?: string;
}

interface TraceRow {
  id: string;
  companyId: string;
}

export class OutcomeEdgeEmitter {
  constructor(private readonly db: PgQueryable) {}

  /**
   * Emit a `results_in` edge for a review disposition.
   * Links the approval decision trace → a new outcome decision trace.
   */
  async emitReviewOutcome(input: ReviewOutcomeInput): Promise<OutcomeEdgeRow | null> {
    const decisionTrace = await this.findTraceBySource(input.companyId, input.approvalSourceId);
    if (!decisionTrace) return null;

    const outcomeLabel = mapReviewOutcome(input.outcome);
    const outcomeSignal = input.outcome === "approved" ? "positive" : "negative";

    const outcomeTraceId = await this.insertOutcomeTrace({
      companyId: input.companyId,
      sourceKind: "approval_resolved",
      sourceId: `${input.approvalSourceId}:outcome`,
      traceType: "review_outcome",
      summary: `Review resolved: ${input.outcome}`,
      outcomeSignal,
      outcomeNote: `Disposition: ${outcomeLabel}`,
      resolvedAt: input.resolvedAt,
      metadata: {
        outcomeType: "review_disposition",
        outcomeLabel,
        approvalSourceId: input.approvalSourceId,
      },
    });

    if (!outcomeTraceId) return null;

    const edge: OutcomeEdgeRow = {
      companyId: input.companyId,
      fromTraceId: decisionTrace.id,
      toTraceId: outcomeTraceId,
      edgeType: "results_in",
      inferredBy: "review_disposition_rule",
      confidence: 0.95,
      metadata: {
        outcomeType: "review_disposition",
        outcomeLabel,
        resolvedAt: input.resolvedAt,
      },
    };

    await this.insertTraceEdge(edge);
    return edge;
  }

  /**
   * Emit a `results_in` edge for a trade outcome.
   * Links the entry decision trace → a new outcome decision trace with PnL label.
   */
  async emitTradeOutcome(input: TradeOutcomeInput): Promise<OutcomeEdgeRow | null> {
    const entryTrace = await this.findTraceBySource(input.companyId, input.entrySourceId);
    if (!entryTrace) return null;

    const label = labelTradeOutcome(input.pnlBps);
    const outcomeSignal = label === "win" ? "positive" : label === "loss" ? "negative" : "neutral";

    const outcomeTraceId = await this.insertOutcomeTrace({
      companyId: input.companyId,
      sourceKind: "trade_exit",
      sourceId: `${input.exitSourceId}:outcome`,
      traceType: "trade_outcome",
      summary: `Trade ${label}: ${input.pnlBps >= 0 ? "+" : ""}${input.pnlBps}bps`,
      outcomeSignal,
      outcomeNote: `PnL: ${input.pnlBps}bps, label: ${label}`,
      resolvedAt: input.resolvedAt,
      metadata: {
        outcomeType: "trade_result",
        outcomeLabel: label,
        pnlBps: input.pnlBps,
        strategyKey: input.strategyKey,
        symbol: input.symbol,
        regime: input.regime,
        entrySourceId: input.entrySourceId,
        exitSourceId: input.exitSourceId,
      },
    });

    if (!outcomeTraceId) return null;

    const edge: OutcomeEdgeRow = {
      companyId: input.companyId,
      fromTraceId: entryTrace.id,
      toTraceId: outcomeTraceId,
      edgeType: "results_in",
      inferredBy: "trade_pnl_rule",
      confidence: 1.0,
      metadata: {
        outcomeType: "trade_result",
        outcomeLabel: label,
        pnlBps: input.pnlBps,
        resolvedAt: input.resolvedAt,
        strategyKey: input.strategyKey,
        symbol: input.symbol,
      },
    };

    await this.insertTraceEdge(edge);
    return edge;
  }

  /**
   * Emit a `results_in` edge for an issue resolution (status → done/cancelled).
   * Links the status-change decision trace → a new resolution outcome trace.
   */
  async emitIssueResolutionOutcome(input: IssueResolutionOutcomeInput): Promise<OutcomeEdgeRow | null> {
    const decisionTrace = await this.findTraceBySource(input.companyId, input.issueSourceId);
    if (!decisionTrace) return null;

    const outcomeLabel = input.toStatus === "done" ? "completed" : "cancelled";
    const outcomeSignal = input.toStatus === "done" ? "positive" : "neutral";

    const outcomeTraceId = await this.insertOutcomeTrace({
      companyId: input.companyId,
      sourceKind: "issue_status_changed",
      sourceId: `${input.issueSourceId}:outcome`,
      traceType: "issue_resolution_outcome",
      summary: `Issue resolved: ${outcomeLabel}`,
      outcomeSignal,
      outcomeNote: `Disposition: ${outcomeLabel}`,
      resolvedAt: input.resolvedAt,
      metadata: {
        outcomeType: "issue_resolution",
        outcomeLabel,
        toStatus: input.toStatus,
      },
    });

    if (!outcomeTraceId) return null;

    const edge: OutcomeEdgeRow = {
      companyId: input.companyId,
      fromTraceId: decisionTrace.id,
      toTraceId: outcomeTraceId,
      edgeType: "results_in",
      inferredBy: "issue_resolution_rule",
      confidence: 0.92,
      metadata: {
        outcomeType: "issue_resolution",
        outcomeLabel,
        resolvedAt: input.resolvedAt,
      },
    };

    await this.insertTraceEdge(edge);
    return edge;
  }

  /**
   * Batch emit trade outcome edges from existing lifecycle data.
   * Scans exit traces that have entry_to_exit lifecycle edges and emits
   * results_in edges for each completed trade.
   */
  async backfillTradeOutcomes(companyId: string): Promise<number> {
    const rows = await this.db.query(
      `SELECT
         dt_exit.id AS exit_trace_id,
         dt_exit.source_id AS exit_source_id,
         dt_exit.outcome_signal AS exit_outcome_signal,
         dt_exit.context_snapshot AS exit_context,
         dt_exit.created_at AS exit_created_at,
         le.from_source_id AS entry_source_id,
         dt_entry.id AS entry_trace_id
       FROM decision_traces dt_exit
       JOIN decision_trace_lifecycle_edges le
         ON le.company_id = dt_exit.company_id
         AND le.to_source_id = dt_exit.source_id
         AND le.edge_type = 'entry_to_exit'
       JOIN decision_traces dt_entry
         ON dt_entry.company_id = dt_exit.company_id
         AND dt_entry.source_id = le.from_source_id
       LEFT JOIN trace_edges te
         ON te.from_trace_id = dt_entry.id
         AND te.edge_type = 'results_in'
       WHERE dt_exit.company_id = $1
         AND dt_exit.trace_type = 'trade_exit'
         AND te.id IS NULL`,
      [companyId],
    );

    let emitted = 0;
    for (const row of rows.rows) {
      const ctx = (row.exit_context as Record<string, unknown>) ?? {};
      const pnlBps = extractNumber(ctx, "pnlBps") ?? extractNumber(ctx, "pnl_bps") ?? 0;

      const result = await this.emitTradeOutcome({
        companyId,
        exitSourceId: row.exit_source_id as string,
        entrySourceId: row.entry_source_id as string,
        pnlBps,
        resolvedAt: (row.exit_created_at as string) ?? new Date().toISOString(),
        strategyKey: extractString(ctx, "strategyKey"),
        symbol: extractString(ctx, "symbol"),
        regime: extractString(ctx, "regime"),
      });
      if (result) emitted += 1;
    }

    return emitted;
  }

  /**
   * Batch emit review outcome edges from existing approval traces.
   */
  async backfillReviewOutcomes(companyId: string): Promise<number> {
    const rows = await this.db.query(
      `SELECT
         dt.id AS trace_id,
         dt.source_id,
         dt.outcome_signal,
         dt.context_snapshot,
         dt.created_at
       FROM decision_traces dt
       LEFT JOIN trace_edges te
         ON te.from_trace_id = dt.id
         AND te.edge_type = 'results_in'
       WHERE dt.company_id = $1
         AND dt.source_kind = 'approval_resolved'
         AND te.id IS NULL`,
      [companyId],
    );

    let emitted = 0;
    for (const row of rows.rows) {
      const ctx = (row.context_snapshot as Record<string, unknown>) ?? {};
      const approvalOutcome = extractString(ctx, "approvalOutcome") as
        | "approved"
        | "rejected"
        | "changes_requested"
        | undefined;
      if (!approvalOutcome) continue;

      const result = await this.emitReviewOutcome({
        companyId,
        approvalSourceId: row.source_id as string,
        outcome: approvalOutcome,
        resolvedAt: (row.created_at as string) ?? new Date().toISOString(),
      });
      if (result) emitted += 1;
    }

    return emitted;
  }

  private async findTraceBySource(companyId: string, sourceId: string): Promise<TraceRow | null> {
    const result = await this.db.query(
      `SELECT id, company_id FROM decision_traces
       WHERE company_id = $1 AND source_id = $2
       LIMIT 1`,
      [companyId, sourceId],
    );
    if (result.rows.length === 0) return null;
    return {
      id: result.rows[0].id as string,
      companyId: result.rows[0].company_id as string,
    };
  }

  private async insertOutcomeTrace(input: {
    companyId: string;
    sourceKind: string;
    sourceId: string;
    traceType: string;
    summary: string;
    outcomeSignal: string;
    outcomeNote: string;
    resolvedAt: string;
    metadata: Record<string, unknown>;
  }): Promise<string | null> {
    const result = await this.db.query(
      `INSERT INTO decision_traces (
         company_id, source_kind, source_id,
         trace_type, summary, outcome_signal, outcome_note,
         context_snapshot
       ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       ON CONFLICT DO NOTHING
       RETURNING id`,
      [
        input.companyId,
        input.sourceKind,
        input.sourceId,
        input.traceType,
        input.summary,
        input.outcomeSignal,
        input.outcomeNote,
        JSON.stringify({
          ...input.metadata,
          resolvedAt: input.resolvedAt,
        }),
      ],
    );
    if (result.rows.length === 0) return null;
    return result.rows[0].id as string;
  }

  private async insertTraceEdge(edge: OutcomeEdgeRow): Promise<void> {
    await this.db.query(
      `INSERT INTO trace_edges (
         company_id, from_trace_id, to_trace_id,
         edge_type, inferred_by, confidence, metadata
       ) VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (from_trace_id, to_trace_id, edge_type) DO NOTHING`,
      [
        edge.companyId,
        edge.fromTraceId,
        edge.toTraceId,
        edge.edgeType,
        edge.inferredBy,
        edge.confidence,
        JSON.stringify(edge.metadata),
      ],
    );
  }
}

function mapReviewOutcome(outcome: "approved" | "rejected" | "changes_requested"): string {
  switch (outcome) {
    case "approved":
      return "approved";
    case "rejected":
      return "rejected";
    case "changes_requested":
      return "changes_requested";
  }
}

function extractNumber(obj: Record<string, unknown>, key: string): number | undefined {
  const val = obj[key];
  if (typeof val === "number" && Number.isFinite(val)) return val;
  if (typeof val === "string") {
    const parsed = Number(val);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function extractString(obj: Record<string, unknown>, key: string): string | undefined {
  const val = obj[key];
  return typeof val === "string" && val.trim() ? val : undefined;
}
