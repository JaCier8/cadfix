# cadfix task image. Everything above `COPY task /task` is the same for every task (and the same as the
# repo's dev image), so Docker builds the heavy layers once.
FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libx11-6 libexpat1 \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

COPY requirements.lock .
RUN pip install --retries 5 -r requirements.lock

# the generic environment code (MCP server, checks, ops); no scenario generator, no reference data
COPY cadfix /opt/cadfix/cadfix
ENV PYTHONPATH=/opt/cadfix CADFIX_TASK_DIR=/task CADFIX_OUT_DIR=/output
RUN mkdir -p /output && python3 -c "import cadfix.env.server, cadfix.checks"

# public task files: task.json, spec.json, parts/*.step
COPY task /task
