import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

describe("ADR-010 §2 OpenFeature import ban", () => {
  it("rejects @openfeature/* imports anywhere under web/src", async () => {
    const eslint = new ESLint({ cwd: process.cwd() });
    const [result] = await eslint.lintText('import { OpenFeature } from "@openfeature/web-sdk";\nexport const client = OpenFeature;\n', {
      filePath: "src/lib/flags.ts",
    });
    expect(result.messages.map((message) => message.ruleId)).toContain("no-restricted-imports");
    expect(result.messages.find((message) => message.ruleId === "no-restricted-imports")?.message).toMatch(/\/v1\/me/);
  }, 30_000);
});
