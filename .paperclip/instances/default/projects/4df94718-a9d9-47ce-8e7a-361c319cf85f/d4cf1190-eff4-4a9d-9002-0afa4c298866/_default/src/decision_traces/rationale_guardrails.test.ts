import { describe, it, expect } from "vitest";
import {
  validateRationalePayload,
  applyGuardrailResult,
  getFieldRequirements,
} from "./rationale_guardrails";
import type { DecisionTraceEventKind, ExtractedDecisionTrace } from "./types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeTrace(overrides: Partial<ExtractedDecisionTrace> = {}): ExtractedDecisionTrace {
  return {
    traceType: "issue_decision",
    summary: "test trace",
    confidence: 0.8,
    tags: ["trade_entry"],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// validateRationalePayload
// ---------------------------------------------------------------------------

describe("validateRationalePayload", () => {
  // -- approval_resolved ---------------------------------------------------

  describe("approval_resolved", () => {
    const kind: DecisionTraceEventKind = "approval_resolved";

    it("passes when rationale, authority, and alternatives are present", () => {
      const trace = makeTrace({
        reasoning: "because the approach was validated in staging",
        authority: { type: "user", reference: "u-1", label: "user_actor" },
        alternatives: ["option A", "option B"],
      });
      const result = validateRationalePayload(kind, trace);
      expect(result.passed).toBe(true);
      expect(result.violations).toHaveLength(0);
      expect(result.tags).toHaveLength(0);
      expect(result.adjustedConfidence).toBe(0.8);
    });

    it("fails when rationale and authority are missing", () => {
      const trace = makeTrace({});
      const result = validateRationalePayload(kind, trace);
      expect(result.passed).toBe(false);
      expect(result.violations.filter((v) => v.level === "required")).toHaveLength(2);
      expect(result.tags).toContain("guardrail:missing:rationale");
      expect(result.tags).toContain("guardrail:missing:authority");
      // alternatives is recommended → hint, not missing
      expect(result.tags).toContain("guardrail:hint:alternatives");
    });

    it("penalizes confidence for missing required fields", () => {
      const trace = makeTrace({ confidence: 0.84 });
      const result = validateRationalePayload(kind, trace);
      // 2 required fields missing → 0.84 - 0.16 = 0.68
      expect(result.adjustedConfidence).toBeCloseTo(0.68, 2);
    });

    it("does not penalize for missing recommended-only fields", () => {
      const trace = makeTrace({
        reasoning: "team agreed this was the safest path",
        authority: { type: "agent", reference: "a-1", label: "agent_actor" },
        // alternatives missing (recommended)
      });
      const result = validateRationalePayload(kind, trace);
      expect(result.passed).toBe(true);
      expect(result.adjustedConfidence).toBe(0.8);
      expect(result.tags).toContain("guardrail:hint:alternatives");
    });
  });

  // -- trade_entry ---------------------------------------------------------

  describe("trade_entry", () => {
    const kind: DecisionTraceEventKind = "trade_entry";

    it("passes with full payload", () => {
      const trace = makeTrace({
        reasoning: "signal strength above threshold for BTC long",
        authority: { type: "agent", reference: "bot-1", label: "agent_actor" },
        alternatives: ["wait for confirmation"],
      });
      const result = validateRationalePayload(kind, trace);
      expect(result.passed).toBe(true);
      expect(result.violations).toHaveLength(0);
    });

    it("fails without rationale", () => {
      const trace = makeTrace({
        authority: { type: "agent", reference: "bot-1", label: "agent_actor" },
      });
      const result = validateRationalePayload(kind, trace);
      expect(result.passed).toBe(false);
      expect(result.violations.some((v) => v.field === "rationale" && v.level === "required")).toBe(true);
    });
  });

  // -- trade_exit ----------------------------------------------------------

  describe("trade_exit", () => {
    const kind: DecisionTraceEventKind = "trade_exit";

    it("requires rationale and authority", () => {
      const trace = makeTrace({});
      const result = validateRationalePayload(kind, trace);
      expect(result.passed).toBe(false);
      expect(result.violations).toHaveLength(2);
      expect(result.tags).toContain("guardrail:missing:rationale");
      expect(result.tags).toContain("guardrail:missing:authority");
    });
  });

  // -- trade_skip ----------------------------------------------------------

  describe("trade_skip", () => {
    const kind: DecisionTraceEventKind = "trade_skip";

    it("requires rationale", () => {
      const trace = makeTrace({});
      const result = validateRationalePayload(kind, trace);
      expect(result.passed).toBe(false);
      expect(result.tags).toContain("guardrail:missing:rationale");
    });

    it("passes with reasoning", () => {
      const trace = makeTrace({ reasoning: "edge below minimum threshold" });
      const result = validateRationalePayload(kind, trace);
      expect(result.passed).toBe(true);
    });
  });

  // -- issue_comment_created (no requirements) -----------------------------

  describe("issue_comment_created (uncovered event type)", () => {
    it("passes with no violations", () => {
      const trace = makeTrace({});
      const result = validateRationalePayload("issue_comment_created", trace);
      expect(result.passed).toBe(true);
      expect(result.violations).toHaveLength(0);
    });
  });

  // -- authority: "unknown" treated as absent ------------------------------

  describe("authority edge cases", () => {
    it("treats authority type 'unknown' as absent", () => {
      const trace = makeTrace({
        reasoning: "because reasons",
        authority: { type: "unknown", label: "implicit_authority" },
      });
      const result = validateRationalePayload("trade_entry", trace);
      expect(result.violations.some((v) => v.field === "authority")).toBe(true);
    });
  });

  // -- rationale minimum length --------------------------------------------

  describe("rationale minimum length", () => {
    it("rejects reasoning shorter than 5 chars", () => {
      const trace = makeTrace({ reasoning: "ok" });
      const result = validateRationalePayload("trade_skip", trace);
      expect(result.passed).toBe(false);
      expect(result.tags).toContain("guardrail:missing:rationale");
    });
  });

  // -- confidence floor ----------------------------------------------------

  describe("confidence floor", () => {
    it("never drops below 0.1", () => {
      const trace = makeTrace({ confidence: 0.15 });
      const result = validateRationalePayload("trade_exit", trace);
      // 0.15 - 0.16 = -0.01 → clamped to 0.1
      expect(result.adjustedConfidence).toBe(0.1);
    });
  });
});

// ---------------------------------------------------------------------------
// applyGuardrailResult
// ---------------------------------------------------------------------------

describe("applyGuardrailResult", () => {
  it("merges tags and updates confidence on the trace", () => {
    const trace = makeTrace({ tags: ["trade_entry"], confidence: 0.86 });
    const result = validateRationalePayload("trade_entry", trace);
    applyGuardrailResult(trace, result);

    expect(trace.tags).toContain("guardrail:missing:rationale");
    expect(trace.confidence).toBe(result.adjustedConfidence);
    expect((trace.contextSnapshot as any).guardrailViolations).toBeDefined();
    expect((trace.contextSnapshot as any).guardrailPassed).toBe(false);
  });

  it("does not add guardrailViolations when there are none", () => {
    const trace = makeTrace({
      reasoning: "strong signal confirmed",
      authority: { type: "agent", reference: "bot", label: "agent_actor" },
      alternatives: ["wait"],
    });
    const result = validateRationalePayload("trade_entry", trace);
    applyGuardrailResult(trace, result);

    expect((trace.contextSnapshot as any)?.guardrailViolations).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// getFieldRequirements
// ---------------------------------------------------------------------------

describe("getFieldRequirements", () => {
  it("returns requirements for known event types", () => {
    const reqs = getFieldRequirements("approval_resolved");
    expect(reqs).toBeDefined();
    expect(reqs!.length).toBeGreaterThan(0);
  });

  it("returns undefined for event types without requirements", () => {
    expect(getFieldRequirements("issue_status_changed")).toBeUndefined();
  });
});
