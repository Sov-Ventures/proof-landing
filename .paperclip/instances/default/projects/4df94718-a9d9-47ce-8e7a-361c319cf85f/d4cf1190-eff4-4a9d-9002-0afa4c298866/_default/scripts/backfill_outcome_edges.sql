-- ZER-1240: Backfill results_in edges for existing data.
-- Run after migration 0007_add_results_in_edge_type.sql has been applied.
--
-- This script creates outcome traces and results_in edges for:
--   1. Trade exits that have entry_to_exit lifecycle edges
--   2. Approval resolutions that have existing decision traces

-- ============================================================
-- 1. Trade outcome edges
-- ============================================================
-- Create outcome traces for trade exits that don't have one yet.
INSERT INTO decision_traces (
  company_id, source_kind, source_id,
  trace_type, summary, outcome_signal, outcome_note,
  context_snapshot
)
SELECT
  dt_exit.company_id,
  'trade_exit',
  dt_exit.source_id || ':outcome',
  'trade_outcome',
  'Trade ' ||
    CASE
      WHEN COALESCE((dt_exit.context_snapshot->>'pnlBps')::real, 0) > 5 THEN 'win'
      WHEN COALESCE((dt_exit.context_snapshot->>'pnlBps')::real, 0) < -5 THEN 'loss'
      ELSE 'flat'
    END || ': ' ||
    COALESCE((dt_exit.context_snapshot->>'pnlBps')::text, '0') || 'bps',
  CASE
    WHEN COALESCE((dt_exit.context_snapshot->>'pnlBps')::real, 0) > 5 THEN 'positive'
    WHEN COALESCE((dt_exit.context_snapshot->>'pnlBps')::real, 0) < -5 THEN 'negative'
    ELSE 'neutral'
  END,
  'PnL: ' || COALESCE((dt_exit.context_snapshot->>'pnlBps')::text, '0') || 'bps',
  jsonb_build_object(
    'outcomeType', 'trade_result',
    'outcomeLabel', CASE
      WHEN COALESCE((dt_exit.context_snapshot->>'pnlBps')::real, 0) > 5 THEN 'win'
      WHEN COALESCE((dt_exit.context_snapshot->>'pnlBps')::real, 0) < -5 THEN 'loss'
      ELSE 'flat'
    END,
    'pnlBps', COALESCE((dt_exit.context_snapshot->>'pnlBps')::real, 0),
    'resolvedAt', dt_exit.created_at
  )
FROM decision_traces dt_exit
JOIN decision_trace_lifecycle_edges le
  ON le.company_id = dt_exit.company_id
  AND le.to_source_id = dt_exit.source_id
  AND le.edge_type = 'entry_to_exit'
WHERE dt_exit.trace_type = 'trade_exit'
  AND NOT EXISTS (
    SELECT 1 FROM decision_traces dt_oc
    WHERE dt_oc.source_id = dt_exit.source_id || ':outcome'
      AND dt_oc.company_id = dt_exit.company_id
  )
ON CONFLICT DO NOTHING;

-- Create results_in edges linking entry traces to outcome traces.
INSERT INTO trace_edges (
  company_id, from_trace_id, to_trace_id,
  edge_type, inferred_by, confidence, metadata
)
SELECT
  dt_entry.company_id,
  dt_entry.id,
  dt_outcome.id,
  'results_in',
  'trade_pnl_backfill',
  1.0,
  jsonb_build_object(
    'outcomeType', 'trade_result',
    'outcomeLabel', dt_outcome.context_snapshot->>'outcomeLabel',
    'pnlBps', (dt_outcome.context_snapshot->>'pnlBps')::real,
    'backfilled', true
  )
FROM decision_traces dt_exit
JOIN decision_trace_lifecycle_edges le
  ON le.company_id = dt_exit.company_id
  AND le.to_source_id = dt_exit.source_id
  AND le.edge_type = 'entry_to_exit'
JOIN decision_traces dt_entry
  ON dt_entry.company_id = dt_exit.company_id
  AND dt_entry.source_id = le.from_source_id
JOIN decision_traces dt_outcome
  ON dt_outcome.company_id = dt_exit.company_id
  AND dt_outcome.source_id = dt_exit.source_id || ':outcome'
WHERE dt_exit.trace_type = 'trade_exit'
ON CONFLICT (from_trace_id, to_trace_id, edge_type) DO NOTHING;

-- ============================================================
-- 2. Review outcome edges
-- ============================================================
-- Create outcome traces for approval resolutions.
INSERT INTO decision_traces (
  company_id, source_kind, source_id,
  trace_type, summary, outcome_signal, outcome_note,
  context_snapshot
)
SELECT
  dt.company_id,
  'approval_resolved',
  dt.source_id || ':outcome',
  'review_outcome',
  'Review resolved: ' || COALESCE(dt.context_snapshot->>'approvalOutcome', 'unknown'),
  CASE
    WHEN dt.context_snapshot->>'approvalOutcome' = 'approved' THEN 'positive'
    ELSE 'negative'
  END,
  'Disposition: ' || COALESCE(dt.context_snapshot->>'approvalOutcome', 'unknown'),
  jsonb_build_object(
    'outcomeType', 'review_disposition',
    'outcomeLabel', COALESCE(dt.context_snapshot->>'approvalOutcome', 'unknown'),
    'resolvedAt', dt.created_at
  )
FROM decision_traces dt
WHERE dt.source_kind = 'approval_resolved'
  AND dt.context_snapshot->>'approvalOutcome' IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM decision_traces dt_oc
    WHERE dt_oc.source_id = dt.source_id || ':outcome'
      AND dt_oc.company_id = dt.company_id
  )
ON CONFLICT DO NOTHING;

-- Create results_in edges for review outcomes.
INSERT INTO trace_edges (
  company_id, from_trace_id, to_trace_id,
  edge_type, inferred_by, confidence, metadata
)
SELECT
  dt.company_id,
  dt.id,
  dt_outcome.id,
  'results_in',
  'review_disposition_backfill',
  0.95,
  jsonb_build_object(
    'outcomeType', 'review_disposition',
    'outcomeLabel', COALESCE(dt.context_snapshot->>'approvalOutcome', 'unknown'),
    'backfilled', true
  )
FROM decision_traces dt
JOIN decision_traces dt_outcome
  ON dt_outcome.company_id = dt.company_id
  AND dt_outcome.source_id = dt.source_id || ':outcome'
WHERE dt.source_kind = 'approval_resolved'
  AND dt.context_snapshot->>'approvalOutcome' IS NOT NULL
ON CONFLICT (from_trace_id, to_trace_id, edge_type) DO NOTHING;

-- ============================================================
-- 3. Verification query
-- ============================================================
SELECT
  edge_type,
  COUNT(*) AS edge_count,
  COUNT(DISTINCT from_trace_id) AS distinct_sources,
  COUNT(DISTINCT to_trace_id) AS distinct_outcomes
FROM trace_edges
WHERE edge_type = 'results_in'
GROUP BY edge_type;
