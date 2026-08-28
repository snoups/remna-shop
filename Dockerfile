FROM ghcr.io/astral-sh/uv:python3.12-alpine AS builder
WORKDIR /opt/remnatrishop
RUN apk add --no-cache git
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --compile-bytecode \
    && rm -rf .venv/lib/python3.12/site-packages/{pip,setuptools,wheel}*

FROM python:3.12-alpine AS final
WORKDIR /opt/remnatrishop

ARG BUILD_TIME
ARG BUILD_BRANCH
ARG BUILD_COMMIT
ARG BUILD_TAG

ENV BUILD_TIME=${BUILD_TIME}
ENV BUILD_BRANCH=${BUILD_BRANCH}
ENV BUILD_COMMIT=${BUILD_COMMIT}
ENV BUILD_TAG=${BUILD_TAG}

RUN apk add --no-cache postgresql-client

COPY --from=builder /opt/remnatrishop/.venv /opt/remnatrishop/.venv
ENV PATH="/opt/remnatrishop/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/remnatrishop

COPY ./src ./src
COPY ./assets /opt/remnatrishop/assets.default

COPY ./docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh
CMD ["./docker-entrypoint.sh"]
