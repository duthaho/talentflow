import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const script = fileURLToPath(new URL("./require-api-client.mjs", import.meta.url));

test("local commands explain how to recover each missing build output", () => {
  const cwd = mkdtempSync(join(process.cwd(), ".api-client-test-"));
  try {
    mkdirSync(join(cwd, "src/lib/api"), { recursive: true });
    for (const files of [[], ["openapi.json"], ["src/lib/api/schema.ts"]]) {
      for (const file of files) writeFileSync(join(cwd, file), "{}");
      const result = spawnSync(process.execPath, [script], { cwd, encoding: "utf8" });
      assert.equal(result.status, 1);
      assert.match(result.stderr, /make api-client/);
      for (const file of ["openapi.json", "src/lib/api/schema.ts"]) {
        if (!files.includes(file)) assert.ok(result.stderr.includes(file));
      }
      for (const file of files) rmSync(join(cwd, file));
    }
    writeFileSync(join(cwd, "openapi.json"), "{}");
    writeFileSync(join(cwd, "src/lib/api/schema.ts"), "export {};");
    const result = spawnSync(process.execPath, [script], { cwd, encoding: "utf8" });
    assert.equal(result.status, 0);
    assert.equal(result.stderr, "");
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});
