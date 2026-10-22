# syntax=docker/dockerfile:1
ARG RUST_IMAGE=rust:1.99.1-slim-trixie
ARG RUNTIME_IMAGE=debian:trixie-slim

FROM ${RUST_IMAGE} AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY Cargo.toml Cargo.lock codexify.config.example.json ./
COPY src/ src/
COPY browser-companion/model-fallback-order.json browser-companion/model-fallback-order.json
COPY docker/install-tunnel.sh /usr/local/bin/install-tunnel
ARG TARGETARCH
RUN mkdir -p /out \
    && sh /usr/local/bin/install-tunnel "$TARGETARCH" src/openai_tunnel.rs /out/tunnel-client-runtime
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    cargo build --locked --release --bin codexify \
    && cp target/release/codexify /out/codexify

FROM ${RUNTIME_IMAGE} AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates curl git jq openssh-client ripgrep tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 codexify \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash codexify \
    && install -d -o 1000 -g 1000 /workspace /home/codexify/.codexify \
    && chmod 700 /home/codexify
ARG OCI_SOURCE=https://github.com/overbit/codexify
ARG OCI_REVISION=unknown
ARG OCI_VERSION=source
LABEL org.opencontainers.image.title="Codexify" \
      org.opencontainers.image.description="Headless Codexify MCP server with a verified OpenAI tunnel runtime" \
      org.opencontainers.image.source=$OCI_SOURCE \
      org.opencontainers.image.revision=$OCI_REVISION \
      org.opencontainers.image.version=$OCI_VERSION \
      org.opencontainers.image.licenses="MIT"
COPY --from=build --chmod=0755 /out/codexify /out/tunnel-client-runtime /usr/local/bin/
COPY --from=build /out/tunnel-licenses/ /usr/share/doc/tunnel-client-runtime/
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/codexify-entrypoint
COPY --chmod=0755 docker/healthcheck.sh /usr/local/bin/codexify-healthcheck
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/doc/codexify/
COPY LICENSES/ /usr/share/doc/codexify/LICENSES/
ENV HOME=/home/codexify \
    CODEXIFY_CONFIG=/home/codexify/.codexify/codexify.config.json
WORKDIR /workspace
USER 1000:1000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=150s --retries=3 \
    CMD ["/usr/local/bin/codexify-healthcheck"]
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/codexify-entrypoint"]
CMD []
