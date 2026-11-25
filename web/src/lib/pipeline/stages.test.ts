import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { ALLOWED_TRANSITIONS, canMove, STAGES } from "./stages";

function backendTransitions(): Record<string, string[]> {
  const source = readFileSync(
    fileURLToPath(new URL("../../../../app/modules/workflow/domain/candidate_state_machine.py", import.meta.url)),
    "utf8",
  );
  const values = Object.fromEntries([...source.matchAll(/^\s+([A-Z_]+) = "([a-z_]+)"$/gm)].map(([, name, value]) => [name, value]));
  const table = source.slice(source.indexOf("_ALLOWED_TRANSITIONS"));
  const entries = [...table.matchAll(/CandidateStage\.([A-Z_]+): frozenset\(\s*(\{[^}]*\})?\s*\)/g)];
  return Object.fromEntries(
    entries.map(([, from, targets]) => [
      values[from],
      [...(targets ?? "").matchAll(/CandidateStage\.([A-Z_]+)/g)].map(([, name]) => values[name]).sort(),
    ]),
  );
}

describe("pipeline stages", () => {
  it("matches the backend state machine", () => {
    const mirrored = Object.fromEntries(STAGES.map((stage) => [stage, [...ALLOWED_TRANSITIONS[stage]].sort()]));
    expect(mirrored).toEqual(backendTransitions());
  });

  it("allows only state-machine moves", () => {
    expect(canMove("applied", "screening")).toBe(true);
    expect(canMove("applied", "hired")).toBe(false);
    expect(canMove("hired", "withdrawn")).toBe(false);
    expect(canMove("applied", "applied")).toBe(false);
    expect(canMove("archived", "screening")).toBe(false);
  });
});
