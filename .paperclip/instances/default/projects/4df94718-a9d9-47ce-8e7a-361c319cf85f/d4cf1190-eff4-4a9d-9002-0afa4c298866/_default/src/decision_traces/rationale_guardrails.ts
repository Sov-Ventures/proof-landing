import type { DecisionTraceEventKind, ExtractedDecisionTrace } from "./types";

/**
 * Rationale payload guardrails (ZER-1238).
 *
 * Validates that extracted decision traces carry the minimum quality fields
 * expected for their event type. Returns structured warnings that the pipeline
 * can persist as tags and context metadata without blocking insertion.
 */

// ---------------------------------------------------------------------------
// Field requirement definitions
// ---------------------------------------------------------------------------

export type GuardrailField = "rationale" | "alternatives" | "authority";

export interface FieldRequirement {
  field: GuardrailField;
  /** "required" emits a warning tag; "recommended" emits a softer hint. */
  level: "required" | "recommended";
}

/**
 * Per-event-type field expectations.
 *
 * "required" fields that are missing produce a `guardrail:missing:<field>` tag
 * and lower the trace confidence. "recommended" fields produce a
 * `guardrail:hint:<field>` tag but leave confidence unchanged.
 */
const FIELD_REQUIREMENTS: Record<string, FieldRequirement[]> = {
  // Approvals must explain *why* and *who*; alternatives are recommended.
  approval_resolved: [
    { field: "rationale", level: "required" },
    { field: "authority", level: "required" },
    { field: "alternatives", level: "recommended" },
  ],
  // Trade entries must justify the decision and cite authority (strategy/actor).
  trade_entry: [
    { field: "rationale", level: "required" },
    { field: "authority", level: "required" },
    { field: "alternatives", level: "recommended" },
  ],
  // Trade exits must explain why now.
  trade_exit: [
    { field: "rationale", level: "required" },
    { field: "authority", level: "required" },
  ],
  // Position adjustments need reasoning.
  position_adjustment: [
    { field: "rationale", level: "required" },
    { field: "authority", level: "recommended" },
  ],
  // Reassignments should explain authority and reasoning.
  issue_reassigned: [
    { field: "rationale", level: "recommended" },
    { field: "authority", level: "required" },
  ],
  // Trade signals benefit from reasoning but are lower commitment.
  trade_signal: [
    { field: "rationale", level: "recommended" },
  ],
  // Skips should explain why the opportunity was passed.
  trade_skip: [
    { field: "rationale", level: "required" },
  ],
};

/** Confidence penalty applied per missing *required* field. */
const REQUIRED_FIELD_PENALTY = 0.08;

// ---------------------------------------------------------------------------
// Validation result
// ---------------------------------------------------------------------------

export interface GuardrailViolation {
  field: GuardrailField;
  level: "required" | "recommended";
  message: string;
}

export interface GuardrailResult {
  /** True when every required field is present. */
  passed: boolean;
  violations: GuardrailViolation[];
  /** Tags to merge into the trace (e.g. "guardrail:missing:rationale"). */
  tags: string[];
  /** Adjusted confidence after penalties. */
  adjustedConfidence: number;
}

// ---------------------------------------------------------------------------
// Field presence checks
// ---------------------------------------------------------------------------

function hasRationale(trace: ExtractedDecisionTrace): boolean {
  return typeof trace.reasoning === "string" && trace.reasoning.trim().length >= 5;
}

function hasAlternatives(trace: ExtractedDecisionTrace): boolean {
  return Array.isArray(trace.alternatives) && trace.alternatives.length > 0;
}

function hasAuthority(trace: ExtractedDecisionTrace): boolean {
  return (
    trace.authority !== undefined &&
    typeof trace.authority.type === "string" &&
    trace.authority.type !== "unknown"
  );
}

const FIELD_CHECKERS: Record<GuardrailField, (t: ExtractedDecisionTrace) => boolean> = {
  rationale: hasRationale,
  alternatives: hasAlternatives,
  authority: hasAuthority,
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Validate an extracted trace against the guardrail requirements for the
 * originating event type. Returns a result with violations, tags, and an
 * adjusted confidence score.
 */
export function validateRationalePayload(
  sourceKind: DecisionTraceEventKind,
  trace: ExtractedDecisionTrace,
): GuardrailResult {
  const requirements = FIELD_REQUIREMENTS[sourceKind];
  if (!requirements) {
    return {
      passed: true,
      violations: [],
      tags: [],
      adjustedConfidence: trace.confidence ?? 0.5,
    };
  }

  const violations: GuardrailViolation[] = [];
  const tags: string[] = [];
  let penalty = 0;

  for (const req of requirements) {
    const present = FIELD_CHECKERS[req.field](trace);
    if (!present) {
      const tagPrefix = req.level === "required" ? "guardrail:missing" : "guardrail:hint";
      tags.push(`${tagPrefix}:${req.field}`);
      violations.push({
        field: req.field,
        level: req.level,
        message: `${req.level} field '${req.field}' is missing or insufficient for ${sourceKind}`,
      });
      if (req.level === "required") {
        penalty += REQUIRED_FIELD_PENALTY;
      }
    }
  }

  const baseConfidence = trace.confidence ?? 0.5;
  const adjustedConfidence = Math.max(0.1, baseConfidence - penalty);
  const passed = violations.every((v) => v.level !== "required");

  return { passed, violations, tags, adjustedConfidence };
}

/**
 * Apply guardrail results to an extracted trace *in place* by merging tags
 * and updating confidence. Returns the same trace reference for chaining.
 */
export function applyGuardrailResult(
  trace: ExtractedDecisionTrace,
  result: GuardrailResult,
): ExtractedDecisionTrace {
  const existingTags = trace.tags ?? [];
  trace.tags = [...existingTags, ...result.tags];
  trace.confidence = result.adjustedConfidence;

  // Persist guardrail metadata in context snapshot for downstream analysis.
  if (result.violations.length > 0) {
    trace.contextSnapshot = {
      ...trace.contextSnapshot,
      guardrailViolations: result.violations.map((v) => ({
        field: v.field,
        level: v.level,
      })),
      guardrailPassed: result.passed,
    };
  }

  return trace;
}

/**
 * Return the field requirements for a given event type (useful for tests
 * and status reporting).
 */
export function getFieldRequirements(
  sourceKind: DecisionTraceEventKind,
): FieldRequirement[] | undefined {
  return FIELD_REQUIREMENTS[sourceKind];
}
