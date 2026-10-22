#!/bin/sh
set -eu
version=0.0.12
case "${1:-}" in
    amd64) sha256=31e9ece3f54f87126813fb206d465fd86b23462cc71734a787927b818f60d931 ;;
    arm64) sha256=f02bc770367e328f21614841eb27393d7f023256224a6dde31c8aa4d6dc763f5 ;;
    *) echo 'Unsupported tunnel runtime architecture (expected amd64 or arm64).' >&2; exit 1 ;;
esac
# Fail the build if upstream changes its pinned runtime without updating this image.
grep -Fq "pub const TUNNEL_CLIENT_VERSION: &str = \"$version\";" src/openai_tunnel.rs
grep -Fq "(\"linux\", \"$1\") => \"$sha256\"" src/openai_tunnel.rs
archive=$(mktemp)
trap 'rm -f "$archive"' 0
curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
    "https://github.com/openai/tunnel-client/releases/download/v$version/tunnel-client-runtime-v$version-linux-$1.zip" \
    --output "$archive"
printf '%s  %s\n' "$sha256" "$archive" | sha256sum --check --status
mkdir -p /out
unzip -p "$archive" tunnel-client-runtime > /out/tunnel-client-runtime
chmod 755 /out/tunnel-client-runtime
