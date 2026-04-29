import type {
  DecisionTraceRecord,
  DecisionTraceWriteEvent,
  TraceEdgeInsert,
  TraceEdgeType,
} from "./types";

export interface TraceEdgeLinker {
  buildEdges(input: {
    trace: DecisionTraceRecord;
    event: DecisionTraceWriteEvent;
    candidates: DecisionTraceRecord[];
  }): TraceEdgeInsert[];
}

export class AutoTraceEdgeLinker implements TraceEdgeLinker {
  constructor(
    private readonly temporalWindowMs: number = 15 * 60 * 1000,
    private readonly actorWindowMs: number = 24 * 60 * 60 * 1000,
  ) {}

  buildEdges(input: {
    trace: DecisionTraceRecord;
    event: DecisionTraceWriteEvent;
    candidates: DecisionTraceRecord[];
  }): TraceEdgeInsert[] {
    const { trace, event, candidates } = input;
    const edges: TraceEdgeInsert[] = [];

    edges.push(...buildExplicitMetadataEdges(trace.id, event.metadata));

    const parentIssueId = asString(event.metadata?.parentIssueId) ?? asString(trace.contextSnapshot?.parentIssueId);
    const traceCreatedAt = toEpochMs(trace.createdAt);

    for (const candidate of candidates) {
      if (candidate.id === trace.id) continue;
      if (candidate.companyId !== trace.companyId) continue;

      const candidateCreatedAt = toEpochMs(candidate.createdAt);
      const elapsedMs = Math.abs(traceCreatedAt - candidateCreatedAt);

      if (trace.issueId && candidate.issueId && trace.issueId === candidate.issueId) {
        edges.push(
          makeEdge(trace.id, candidate.id, "informed_by", "issue_hierarchy_same_issue", 0.78, {
            rule: "same_issue",
          }),
        );
      }

      if (parentIssueId && candidate.issueId === parentIssueId) {
        edges.push(
          makeEdge(trace.id, candidate.id, "caused_by", "issue_hierarchy_parent_issue", 0.83, {
            rule: "parent_issue",
            parentIssueId,
          }),
        );
      }

      if (elapsedMs <= this.temporalWindowMs && sharesProjectOrGoal(trace, candidate)) {
        edges.push(
          makeEdge(trace.id, candidate.id, "informed_by", "temporal_proximity", 0.64, {
            rule: "temporal_proximity",
            elapsedMs,
          }),
        );
      }

      if (elapsedMs <= this.actorWindowMs && sameActor(trace, candidate)) {
        const edgeType: TraceEdgeType = hasConfigTag(trace) || hasConfigTag(candidate) ? "config_change" : "supersedes";
        edges.push(
          makeEdge(trace.id, candidate.id, edgeType, "actor_correlation", 0.61, {
            rule: "actor_correlation",
            elapsedMs,
            sameActor: true,
          }),
        );
      }

      if (trace.issueId && candidate.issueId && trace.issueId === candidate.issueId && hasContradictingSignals(trace, candidate)) {
        edges.push(
          makeEdge(trace.id, candidate.id, "contradicts", "signal_contradiction", 0.7, {
            rule: "signal_contradiction",
            fromSignal: trace.outcomeSignal,
            toSignal: candidate.outcomeSignal,
          }),
        );
      }
    }

    return dedupeEdges(edges);
  }
}

function buildExplicitMetadataEdges(traceId: string, metadata?: Record<string, unknown>): TraceEdgeInsert[] {
  if (!metadata) return [];

  const explicitMappings: Array<{ key: string; type: TraceEdgeType }> = [
    { key: "causedByTraceId", type: "caused_by" },
    { key: "supersedesTraceId", type: "supersedes" },
    { key: "informedByTraceId", type: "informed_by" },
    { key: "contradictsTraceId", type: "contradicts" },
    { key: "escalatedToTraceId", type: "escalated_to" },
    { key: "resolvedByTraceId", type: "resolved_by" },
    { key: "signalToEntryTraceId", type: "signal_to_entry" },
    { key: "entryToExitTraceId", type: "entry_to_exit" },
    { key: "configChangeTraceId", type: "config_change" },
    { key: "resultsInTraceId", type: "results_in" },
  ];

  return explicitMappings
    .map((mapping) => {
      const linkedTraceId = asString(metadata[mapping.key]);
      if (!linkedTraceId || linkedTraceId === traceId) return null;
      return makeEdge(traceId, linkedTraceId, mapping.type, "explicit_metadata", 0.95, {
        rule: "explicit_metadata",
        key: mapping.key,
      });
    })
    .filter((edge): edge is TraceEdgeInsert => edge !== null);
}

function makeEdge(
  fromTraceId: string,
  toTraceId: string,
  edgeType: TraceEdgeType,
  inferredBy: string,
  confidence: number,
  metadata: Record<string, unknown>,
): TraceEdgeInsert {
  return {
    fromTraceId,
    toTraceId,
    edgeType,
    inferredBy,
    confidence,
    metadata,
  };
}

function dedupeEdges(edges: TraceEdgeInsert[]): TraceEdgeInsert[] {
  const unique = new Map<string, TraceEdgeInsert>();
  for (const edge of edges) {
    if (edge.fromTraceId === edge.toTraceId) continue;
    const key = `${edge.fromTraceId}:${edge.toTraceId}:${edge.edgeType}`;
    if (!unique.has(key)) unique.set(key, edge);
  }
  return [...unique.values()];
}

function sharesProjectOrGoal(a: DecisionTraceRecord, b: DecisionTraceRecord): boolean {
  return (Boolean(a.projectId) && a.projectId === b.projectId) || (Boolean(a.goalId) && a.goalId === b.goalId);
}

function sameActor(a: DecisionTraceRecord, b: DecisionTraceRecord): boolean {
  if (a.actorAgentId && b.actorAgentId && a.actorAgentId === b.actorAgentId) return true;
  if (a.actorUserId && b.actorUserId && a.actorUserId === b.actorUserId) return true;
  return false;
}

function hasConfigTag(trace: DecisionTraceRecord): boolean {
  return (trace.tags ?? []).some((tag) => /config/i.test(tag));
}

function hasContradictingSignals(a: DecisionTraceRecord, b: DecisionTraceRecord): boolean {
  const left = normalizeSignal(a.outcomeSignal);
  const right = normalizeSignal(b.outcomeSignal);
  return Boolean(left && right && left !== right);
}

function normalizeSignal(signal?: string): "positive" | "negative" | null {
  if (!signal) return null;
  const normalized = signal.trim().toLowerCase();
  if (["up", "positive", "approved", "go", "buy", "open"].includes(normalized)) return "positive";
  if (["down", "negative", "rejected", "no_go", "sell", "close"].includes(normalized)) return "negative";
  return null;
}

function toEpochMs(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}
