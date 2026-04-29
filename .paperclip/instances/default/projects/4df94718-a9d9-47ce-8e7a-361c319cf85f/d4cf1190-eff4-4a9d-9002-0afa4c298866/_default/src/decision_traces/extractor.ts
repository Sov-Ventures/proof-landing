import type { DecisionTraceWriteEvent, ExtractedDecisionTrace, TradeTraceType } from "./types";

export interface DecisionExtractor {
  extract(event: DecisionTraceWriteEvent): Promise<ExtractedDecisionTrace | null>;
}

export class HeuristicDecisionExtractor implements DecisionExtractor {
  async extract(event: DecisionTraceWriteEvent): Promise<ExtractedDecisionTrace | null> {
    const text = normalizeText(event.body);
    if (!text) return null;

    const hasDecisionVerb = /(decide|approved|rejected|blocked|assign|reassign|ship|merge|enter|exit|skip|adjust)/.test(text);
    const hasReasoningCue = /(because|due to|so that|reason|risk|tradeoff)/.test(text);
    const isTradeEvent = isTradeSourceKind(event.sourceKind);

    if (!isTradeEvent && !hasDecisionVerb && !hasReasoningCue) {
      return null;
    }

    return {
      traceType: mapTraceType(event.sourceKind, text),
      summary: summarize(text),
      reasoning: hasReasoningCue ? summarizeReasoning(text) : undefined,
      alternatives: deriveAlternatives(text),
      authority: deriveAuthority(event, text),
      outcomeSignal: deriveOutcomeSignal(event.sourceKind, text),
      tags: deriveTags(event, text),
      confidence: scoreConfidence(hasDecisionVerb, hasReasoningCue, isTradeEvent),
      contextSnapshot: {
        sourceKind: event.sourceKind,
        occurredAt: event.occurredAt,
        metadata: event.metadata ?? {},
      },
    };
  }
}

function normalizeText(input: string): string {
  return input.replace(/\s+/g, " ").trim().toLowerCase();
}

function mapTraceType(sourceKind: DecisionTraceWriteEvent["sourceKind"], text: string): string {
  if (isTradeSourceKind(sourceKind)) return sourceKind;
  if (sourceKind === "approval_resolved") return "approval_decision";
  if (sourceKind === "issue_reassigned") return "assignment_decision";
  if (/blocked/.test(text)) return "escalation_decision";
  return "issue_decision";
}

function summarize(text: string): string {
  return text.slice(0, 280);
}

function summarizeReasoning(text: string): string | undefined {
  const match = text.match(/(?:because|due to|reason)\s+(.+?)(?:\.|$)/);
  return match?.[1]?.slice(0, 280);
}

function deriveAlternatives(text: string): string[] | undefined {
  const alternatives = new Set<string>();

  const listMatch = text.match(/(?:alternatives?|options?)\s*:\s*([^.;]+)/);
  if (listMatch?.[1]) {
    for (const candidate of splitAlternatives(listMatch[1])) {
      alternatives.add(candidate);
    }
  }

  const versusMatch = text.match(/(?:vs\.?|versus|instead of)\s+([^.;]+)/);
  if (versusMatch?.[1]) {
    for (const candidate of splitAlternatives(versusMatch[1])) {
      alternatives.add(candidate);
    }
  }

  if (alternatives.size === 0) return undefined;
  return [...alternatives].slice(0, 6);
}

function splitAlternatives(raw: string): string[] {
  return raw
    .split(/,|\/|\bor\b/)
    .map((item) => item.trim())
    .filter((item) => item.length >= 3)
    .slice(0, 8);
}

function deriveAuthority(
  event: DecisionTraceWriteEvent,
  text: string,
): ExtractedDecisionTrace["authority"] | undefined {
  if (event.actorAgentId) {
    return {
      type: "agent",
      reference: event.actorAgentId,
      label: "agent_actor",
    };
  }

  if (event.actorUserId) {
    return {
      type: "user",
      reference: event.actorUserId,
      label: "user_actor",
    };
  }

  if (/board/.test(text)) {
    return {
      type: "board",
      label: "board",
    };
  }

  const roleMatch = text.match(/\b(ceo|cto|manager|lead|owner|approver)\b/);
  if (roleMatch?.[1]) {
    return {
      type: "role",
      label: roleMatch[1],
    };
  }

  if (/approved|rejected|decide/.test(text)) {
    return {
      type: "unknown",
      label: "implicit_authority",
    };
  }

  return undefined;
}

function deriveOutcomeSignal(sourceKind: DecisionTraceWriteEvent["sourceKind"], text: string): string | undefined {
  if (sourceKind === "trade_entry") return "entered_position";
  if (sourceKind === "trade_exit") return "exited_position";
  if (sourceKind === "trade_skip") return "skipped_trade";
  if (sourceKind === "position_adjustment") return "adjusted_position";
  if (/approved/.test(text)) return "approved";
  if (/rejected/.test(text)) return "rejected";
  if (/blocked/.test(text)) return "blocked";
  return undefined;
}

function deriveTags(event: DecisionTraceWriteEvent, text: string): string[] {
  const tags = new Set<string>([event.sourceKind]);

  if (/risk/.test(text)) tags.add("risk");
  if (/tradeoff/.test(text)) tags.add("tradeoff");
  if (/approve|approved/.test(text)) tags.add("approval");
  if (/block|blocked/.test(text)) tags.add("blocked");

  const strategy = event.metadata?.strategyKey;
  const symbol = event.metadata?.symbol;
  if (typeof strategy === "string" && strategy.trim()) tags.add(`strategy:${strategy}`);
  if (typeof symbol === "string" && symbol.trim()) tags.add(`symbol:${symbol}`);

  return [...tags];
}

function scoreConfidence(hasDecisionVerb: boolean, hasReasoningCue: boolean, isTradeEvent: boolean): number {
  if (isTradeEvent && hasReasoningCue) return 0.9;
  if (isTradeEvent) return 0.86;
  if (hasDecisionVerb && hasReasoningCue) return 0.84;
  if (hasDecisionVerb) return 0.72;
  return 0.55;
}

function isTradeSourceKind(sourceKind: DecisionTraceWriteEvent["sourceKind"]): sourceKind is TradeTraceType {
  return (
    sourceKind === "trade_signal" ||
    sourceKind === "trade_entry" ||
    sourceKind === "trade_exit" ||
    sourceKind === "position_adjustment" ||
    sourceKind === "trade_skip"
  );
}
