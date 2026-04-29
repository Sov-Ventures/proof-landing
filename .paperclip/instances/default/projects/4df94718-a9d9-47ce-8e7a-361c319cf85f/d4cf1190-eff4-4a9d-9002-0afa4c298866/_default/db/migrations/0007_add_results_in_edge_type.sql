-- Sprint 1 (ZER-1240): Add results_in edge type for outcome linkage.
-- Connects decision traces to their realized outcomes (review dispositions, trade PnL).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_enum
    WHERE enumlabel = 'results_in'
      AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'trace_edge_type')
  ) THEN
    ALTER TYPE trace_edge_type ADD VALUE 'results_in';
  END IF;
END;
$$;
