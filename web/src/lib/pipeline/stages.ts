export const STAGES = [
  "applied",
  "screening",
  "interviewing",
  "offer_pending_approval",
  "offer_approved",
  "offer_rejected",
  "hired",
  "rejected",
  "withdrawn",
] as const;

export type Stage = (typeof STAGES)[number];

export const STAGE_LABELS: Record<Stage, string> = {
  applied: "Applied",
  screening: "Screening",
  interviewing: "Interviewing",
  offer_pending_approval: "Offer pending",
  offer_approved: "Offer approved",
  offer_rejected: "Offer rejected",
  hired: "Hired",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

// Mirror of _ALLOWED_TRANSITIONS in app/modules/workflow/domain/candidate_state_machine.py;
// stages.test.ts fails when the two drift. The API stays the authority and answers 422 on an illegal move.
export const ALLOWED_TRANSITIONS: Record<Stage, readonly Stage[]> = {
  applied: ["screening", "rejected", "withdrawn"],
  screening: ["interviewing", "rejected", "withdrawn"],
  interviewing: ["offer_pending_approval", "rejected", "withdrawn"],
  offer_pending_approval: ["offer_approved", "offer_rejected", "withdrawn"],
  offer_approved: ["hired", "withdrawn"],
  offer_rejected: ["rejected", "withdrawn"],
  hired: [],
  rejected: [],
  withdrawn: [],
};

// Offer stages are rendered as columns, but only offer endpoints may target them.
// This table governs moves submitted to the generic candidate stage endpoint.
export const GENERIC_STAGE_TRANSITIONS: Record<Stage, readonly Stage[]> = Object.fromEntries(
  STAGES.map((stage) => [
    stage,
    ALLOWED_TRANSITIONS[stage].filter(
      (target) => !["offer_pending_approval", "offer_approved", "offer_rejected"].includes(target),
    ),
  ]),
) as Record<Stage, readonly Stage[]>;

export function isStage(value: string): value is Stage {
  return (STAGES as readonly string[]).includes(value);
}

export function canMove(from: string, to: Stage): boolean {
  return isStage(from) && GENERIC_STAGE_TRANSITIONS[from].includes(to);
}
