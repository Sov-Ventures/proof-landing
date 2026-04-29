import type { DecisionTracePipeline } from "./pipeline";
import type { DecisionTraceEventKind, DecisionTraceWriteEvent } from "./types";

export interface PolybotTradeRow {
  id: string;
  created_at: string;
  script: string;
  event_type: string;
  symbol?: string | null;
  position_id?: string | null;
  order_id?: string | null;
  message?: string | null;
  payload_json?: Record<string, unknown> | null;
}

export interface PolybotBatchSyncOptions {
  companyId: string;
  issueId?: string;
  projectId?: string;
  goalId?: string;
  actorAgentId?: string;
  sourceRunId?: string;
}

export interface PolybotBatchSyncResult {
  processed: number;
  emitted: number;
  skipped: number;
}

export async function syncPolybotRows(
  rows: PolybotTradeRow[],
  pipeline: DecisionTracePipeline,
  options: PolybotBatchSyncOptions,
): Promise<PolybotBatchSyncResult> {
  let emitted = 0;
  let skipped = 0;

  for (const row of rows) {
    const sourceKind = mapPolybotEventType(row.event_type);
    if (!sourceKind) {
      skipped += 1;
      continue;
    }

    const rawPayload = row.payload_json ?? {};
    const lifecycleEdgeRaw = rawPayload.lifecycle_edge as { type?: string; from_event_id?: string } | undefined;

    const event: DecisionTraceWriteEvent = {
      companyId: options.companyId,
      issueId: options.issueId,
      projectId: options.projectId,
      goalId: options.goalId,
      sourceKind,
      sourceId: row.id,
      sourceRunId: options.sourceRunId,
      actorAgentId: options.actorAgentId,
      occurredAt: row.created_at,
      body: row.message?.trim() || `polybot ${row.script} ${row.event_type}`,
      metadata: {
        strategyKey: row.script,
        symbol: row.symbol ?? undefined,
        positionId: row.position_id ?? undefined,
        orderId: row.order_id ?? undefined,
        syncSource: "polybot.db",
        rawPayload,
        ...(lifecycleEdgeRaw?.from_event_id
          ? {
              lifecycleEdge: {
                edgeType: lifecycleEdgeRaw.type === "signal_to_entry" ? "signal_to_entry" as const
                  : lifecycleEdgeRaw.type === "entry_to_exit" ? "entry_to_exit" as const
                  : "config_change" as const,
                fromSourceId: lifecycleEdgeRaw.from_event_id,
              },
            }
          : {}),
      },
    };

    const accepted = await pipeline.handleWriteEvent(event);
    if (accepted) {
      emitted += 1;
    } else {
      skipped += 1;
    }
  }

  return {
    processed: rows.length,
    emitted,
    skipped,
  };
}

function mapPolybotEventType(eventType: string): DecisionTraceEventKind | null {
  const normalized = eventType.trim().toLowerCase();
  if (normalized === "signal") return "trade_signal";
  if (normalized === "entry") return "trade_entry";
  if (normalized === "exit") return "trade_exit";
  if (normalized === "adjustment" || normalized === "position_adjustment") return "position_adjustment";
  if (normalized === "skip" || normalized === "trade_skip") return "trade_skip";
  return null;
}
