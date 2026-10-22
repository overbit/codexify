#!/bin/sh
set -eu
# Local HTTP liveness only; tunnel readiness is supervised by Codexify itself.
port=$(jq -er '.port // 3000 | select(type == "number" and . >= 1 and . <= 65535 and floor == .)' "$CODEXIFY_CONFIG")
exec curl --fail --silent --show-error --noproxy '*' --max-time 3 "http://127.0.0.1:$port/health"
