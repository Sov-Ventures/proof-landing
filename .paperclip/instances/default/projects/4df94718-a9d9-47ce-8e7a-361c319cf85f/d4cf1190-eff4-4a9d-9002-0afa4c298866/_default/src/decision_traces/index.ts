export type {
  DecisionTraceEventKind,
  DecisionTraceWriteEvent,
  ExtractedDecisionTrace,
  DecisionTraceRecord,
  TraceEdgeType,
  TraceEdgeInsert,
  TradeTraceType,
  TradeLifecycleEdgeType,
  DecisionTraceLifecycleEdgeHint,
  DecisionTraceEventMetadata,
} from "./types";

export { DecisionTracePipeline } from "./pipeline";
export type { DecisionTraceRepository } from "./pipeline";
export { DecisionTraceHooks } from "./event_hooks";
export { HeuristicDecisionExtractor } from "./extractor";
export type { DecisionExtractor } from "./extractor";
export { PostgresDecisionTraceRepository } from "./repository";
export type { PgQueryable } from "./repository";
export {
  PaperclipDecisionTraceBridge,
  type PaperclipIssueCommentCreatedEvent,
  type PaperclipIssueStatusChangedEvent,
  type PaperclipIssueReassignedEvent,
  type PaperclipApprovalResolvedEvent,
} from "./paperclip_write_path";
export { OutcomeEdgeEmitter } from "./outcome_edge_emitter";
export type { OutcomeEdgeRow, ReviewOutcomeInput, TradeOutcomeInput } from "./outcome_edge_emitter";

import type { PgQueryable } from "./repository";
import { PostgresDecisionTraceRepository } from "./repository";
import { HeuristicDecisionExtractor } from "./extractor";
import { DecisionTracePipeline } from "./pipeline";
import { DecisionTraceHooks } from "./event_hooks";
import { PaperclipDecisionTraceBridge } from "./paperclip_write_path";
import { OutcomeEdgeEmitter } from "./outcome_edge_emitter";

/**
 * Factory: create the full Phase 1a stack from a Postgres connection.
 * Returns the bridge (Paperclip write-path adapter) and the underlying pipeline.
 */
export function createDecisionTraceStack(db: PgQueryable) {
  const repository = new PostgresDecisionTraceRepository(db);
  const extractor = new HeuristicDecisionExtractor();
  const outcomeEmitter = new OutcomeEdgeEmitter(db);
  const pipeline = new DecisionTracePipeline(extractor, repository, outcomeEmitter);
  const hooks = new DecisionTraceHooks(pipeline);
  const bridge = new PaperclipDecisionTraceBridge(hooks);

  return { bridge, pipeline, hooks, repository, extractor, outcomeEmitter };
}
