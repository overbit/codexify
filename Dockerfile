# syntax=docker/dockerfile:1
ARG RUST_IMAGE=rust:1.99.1-slim-trixie
ARG RUNTIME_IMAGE=debian:trixie-slim

FROM ${RUST_IMAGE} AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY Cargo.toml Cargo.lock codexify.config.example.json ./
COPY src ./src
COPY browser-companion/model-fallback-order.json ./browser-companion/model-fallback-order.json
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cargo build --locked --release --bin codexify \
    && install -Dm755 target/release/codexify /out/codexify
# Ship the verified tunnel runtime, rather than downloading executable code at startup.
ARG TARGETARCH
COPY docker/install-tunnel.sh /tmp/install-tunnel.sh
RUN sh /tmp/install-tunnel.sh "$TARGETARCH"

FROM ${RUNTIME_IMAGE} AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates curl git jq openssh-client ripgrep tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 codexify \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash codexify \
    && mkdir -p /workspace /home/codexify/.codexify \
    && chown -R 1000:1000 /workspace /home/codexify
ARG OCI_SOURCE=https://github.com/overbit/codexify
ARG OCI_REVISION=unknown
ARG OCI_VERSION=source
LABEL org.opencontainers.image.title="Codexify" \
      org.opencontainers.image.description="Headless Codexify MCP server with a verified OpenAI tunnel runtime" \
      org.opencontainers.image.source=$OCI_SOURCE \
      org.opencontainers.image.revision=$OCI_REVISION \
      org.opencontainers.image.version=$OCI_VERSION \
      org.opencontainers.image.licenses="MIT"
COPY --from=build /out/codexify /out/tunnel-client-runtime /usr/local/bin/
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/codexify-entrypoint
COPY --chmod=755 docker/healthcheck.sh /usr/local/bin/codexify-healthcheck
COPY docker/codexify.config.json /etc/codexify/codexify.config.json
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/doc/codexify/
COPY LICENSES /usr/share/doc/codexify/LICENSES
ENV HOME=/home/codexify \
    CODEXIFY_CONFIG=/home/codexify/.codexify/codexify.config.json
WORKDIR /workspace
USER 1000:1000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=150s --retries=3 \
    CMD ["/usr/local/bin/codexify-healthcheck"]
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/codexify-entrypoint"]
CMD []
