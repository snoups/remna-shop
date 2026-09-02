FROM ghcr.io/astral-sh/uv:python3.12-alpine AS builder
WORKDIR /opt/remnashop
RUN apk add --no-cache git
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --compile-bytecode \
    && rm -rf .venv/lib/python3.12/site-packages/{pip,setuptools,wheel}*

FROM python:3.12-alpine AS final
WORKDIR /opt/remnashop

ARG BUILD_TIME
ARG BUILD_BRANCH
ARG BUILD_COMMIT
ARG BUILD_TAG

ENV BUILD_TIME=${BUILD_TIME}
ENV BUILD_BRANCH=${BUILD_BRANCH}
ENV BUILD_COMMIT=${BUILD_COMMIT}
ENV BUILD_TAG=${BUILD_TAG}

RUN apk add --no-cache postgresql-client

COPY --from=builder /opt/remnashop/.venv /opt/remnashop/.venv
ENV PATH="/opt/remnashop/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/remnashop

COPY ./src ./src
COPY ./assets /opt/remnashop/assets.default

# Release builds must use a real application version (for example, v0.8.3).
# Docker image names and commit identifiers belong in the image tag/labels,
# not in BUILD_TAG, because the hourly update task parses this value.
RUN if [ -n "$BUILD_TAG" ] && [ "$BUILD_TAG" != "dev" ]; then \
        python -c 'import sys; from packaging.version import Version; Version(sys.argv[1].removeprefix("v"))' "$BUILD_TAG"; \
    fi

COPY ./docker-entrypoint.sh ./docker-entrypoint.sh
COPY ./docker-migrate.sh ./docker-migrate.sh
RUN sed -i 's/\r$//' ./docker-entrypoint.sh \
    && sed -i 's/\r$//' ./docker-migrate.sh \
    && chmod +x ./docker-entrypoint.sh ./docker-migrate.sh
CMD ["./docker-entrypoint.sh"]
