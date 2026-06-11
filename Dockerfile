# Railway cron service image: the daily unattended trading run.
# Entrypoint = scripts/daily_cron.py via docker-entrypoint.sh, which
# seeds + symlinks data/, reports/, logs/ onto the single Railway
# volume (/persist). See docs/railway_deploy.md.

# Overridable for registries that mirror the official image (rate limits):
#   docker build --build-arg BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim .
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

# uv is needed at runtime too: run_daily_pipeline spawns its steps as
# `uv run python -m <module>` subprocesses. PyPI install (not the ghcr
# COPY --from image) keeps the build to a single registry.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer first so code edits don't bust the package cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# The synced venv on PATH means `python` == the project interpreter for
# both the entrypoint and every child process daily_cron spawns.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
