import type { DecisionTraceRepository } from "./pipeline";
import type { ExtractedDecisionTrace, TradeLifecycleEdgeType, TraceEdgeType } from "./types";

/**
 * Postgres-backed repository for decision trace persistence.
 * Expects a pg Pool or compatible query interface.
 */
export interface PgQueryable {
  query(text: string, values?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
}

export class PostgresDecisionTraceRepository implements DecisionTraceRepository {
  constructor(private readonly db: PgQueryable) {}

  async insert(input: {
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
  }): Promise<void> {
    const sql = `
      INSERT INTO decision_traces (
        company_id, issue_id, project_id, goal_id,
        source_kind, source_id, source_run_id,
        actor_agent_id, actor_user_id,
        trace_type, summary, reasoning,
        alternatives, authority_type, authority_ref, authority_label,
        outcome_signal, outcome_note,
        tags, confidence, context_snapshot
      ) VALUES (
        $1, $2, $3, $4,
        $5, $6, $7,
        $8, $9,
        $10, $11, $12,
        $13, $14, $15, $16,
        $17, $18,
        $19, $20, $21
      )
    `;

    const values = [
      input.companyId,
      input.issueId ?? null,
      input.projectId ?? null,
      input.goalId ?? null,
      input.sourceKind,
      input.sourceId,
      input.sourceRunId ?? null,
      input.actorAgentId ?? null,
      input.actorUserId ?? null,
      input.extracted.traceType,
      input.extracted.summary,
      input.extracted.reasoning ?? null,
      input.alternatives ?? [],
      input.authority?.type ?? null,
      input.authority?.reference ?? null,
      input.authority?.label ?? null,
      input.extracted.outcomeSignal ?? null,
      input.extracted.outcomeNote ?? null,
      input.extracted.tags ?? [],
      input.extracted.confidence ?? null,
      JSON.stringify(input.extracted.contextSnapshot ?? {}),
    ];

    await this.db.query(sql, values);
  }

  async insertLifecycleEdge(input: {
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
  }): Promise<void> {
    const sql = `
      INSERT INTO decision_trace_lifecycle_edges (
        company_id, issue_id, project_id, goal_id,
        edge_type, from_source_id, to_source_id,
        from_trace_type, to_trace_type, metadata
      ) VALUES (
        $1, $2, $3, $4,
        $5, $6, $7,
        $8, $9, $10
      )
    `;

    const values = [
      input.companyId,
      input.issueId ?? null,
      input.projectId ?? null,
      input.goalId ?? null,
      input.edgeType,
      input.fromSourceId,
      input.toSourceId,
      input.fromTraceType ?? null,
      input.toTraceType ?? null,
      JSON.stringify(input.metadata ?? {}),
    ];

    await this.db.query(sql, values);
  }

  async insertTraceEdge(input: {
    companyId: string;
    fromTraceId: string;
    toTraceId: string;
    edgeType: TraceEdgeType;
    inferredBy: string;
    confidence?: number;
    metadata?: Record<string, unknown>;
  }): Promise<void> {
    const sql = `
      INSERT INTO trace_edges (
        company_id, from_trace_id, to_trace_id,
        edge_type, inferred_by, confidence, metadata
      ) VALUES ($1, $2, $3, $4, $5, $6, $7)
      ON CONFLICT (from_trace_id, to_trace_id, edge_type) DO NOTHING
    `;

    const values = [
      input.companyId,
      input.fromTraceId,
      input.toTraceId,
      input.edgeType,
      input.inferredBy,
      input.confidence ?? null,
      JSON.stringify(input.metadata ?? {}),
    ];

    await this.db.query(sql, values);
  }
}
