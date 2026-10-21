FROM python:3.13-slim

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md alembic.ini ./
# Apply fixed Debian packages and keep Python packaging tools outside known vulnerable ranges.
RUN apt-get update \
    && apt-get upgrade --yes \
    && python -m pip install --no-cache-dir 'pip>=26.0' 'setuptools>=82.0' 'certifi>=2026.10.19' \
    && rm -rf /var/lib/apt/lists/* \
    && uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY migrations ./migrations
RUN uv sync --frozen --no-dev \
    && groupadd --system talentflow \
    && useradd --system --gid talentflow --home-dir /app talentflow \
    && chown -R talentflow:talentflow /app

ENV PATH="/app/.venv/bin:$PATH"
USER talentflow
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
