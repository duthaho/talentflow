import { existsSync } from "node:fs";

const missing = ["openapi.json", "src/lib/api/schema.ts"].filter(
  (file) => !existsSync(file),
);

if (missing.length) {
  console.error(
    `Missing generated API client: ${missing.join(", ")}.\n` +
      "From the repository root, run: uv sync --python 3.13 --frozen && npm --prefix web ci && make api-client\n" +
      "Run make api-client again after changing backend routes or switching branches.",
  );
  process.exit(1);
}
