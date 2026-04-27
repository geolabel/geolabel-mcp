# syntax=docker/dockerfile:1.7
#
# GeoLabel MCP server image.
#
# Two-stage build: a builder stage installs the package and its
# dependencies into a virtualenv; the runtime stage copies that
# virtualenv into a slim, non-root image. Final image is ~100 MB.

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY geolabel_mcp ./geolabel_mcp

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install .

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root user — the MCP server has no need for elevated privileges.
RUN groupadd --system --gid 1001 geolabel && \
    useradd --system --uid 1001 --gid geolabel --no-create-home --shell /sbin/nologin geolabel

COPY --from=builder /opt/venv /opt/venv

USER geolabel
WORKDIR /home/geolabel

ENTRYPOINT ["geolabel-mcp"]
