# The root context provides the exact backend contract for this checkout.
FROM python:3.13.9-slim AS schema
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY scripts ./scripts
RUN uv run --no-sync python -m scripts.export_openapi /app/openapi.json

FROM node:22.22-alpine AS deps
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22.22-alpine AS build
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /web/node_modules ./node_modules
COPY web/ .
COPY --from=schema /app/openapi.json ./openapi.json
RUN npm run api:generate && npm run build

FROM node:22.22-alpine AS runtime
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
RUN addgroup --system talentflow && adduser --system --ingroup talentflow talentflow
COPY --from=build --chown=talentflow:talentflow /web/.next/standalone ./
COPY --from=build --chown=talentflow:talentflow /web/.next/static ./.next/static
COPY --from=build --chown=talentflow:talentflow /web/public ./public
USER talentflow
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/signed-out || exit 1
CMD ["node", "server.js"]
