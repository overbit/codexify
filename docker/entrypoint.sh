#!/bin/sh
set -eu
umask 077

fail() {
    printf 'codexify container: %s\n' "$*" >&2
    exit 1
}

export CODEXIFY_CONFIG="${CODEXIFY_CONFIG:-$HOME/.codexify/codexify.config.json}"
case "${1:-}" in
    -h|--help) exec codexify "$@" ;;
    quickstart|service|update|browser)
        fail 'Use a configured foreground server in this image; see docs/DOCKER.md.' ;;
esac

# Compose file-backed secrets do not consistently support uid/mode overrides.
# Keep Codexify's strict file-key permissions instead of weakening its validator.
secret_file="${CODEXIFY_TUNNEL_API_KEY_FILE:-/run/secrets/openai_tunnel_api_key}"
if [ -e "$secret_file" ]; then
    [ -f "$secret_file" ] && [ -r "$secret_file" ] || fail 'Tunnel secret must be a readable regular file.'
    secret_dir="${TMPDIR:-/tmp}/codexify-secrets"
    [ ! -L "$secret_dir" ] || fail 'Private secret directory must not be a symlink.'
    mkdir -p -m 700 "$secret_dir"
    chmod 700 "$secret_dir"
    secret_tmp=$(mktemp "$secret_dir/key.XXXXXX")
    trap 'rm -f "$secret_tmp"' 0
    cat "$secret_file" > "$secret_tmp"
    mv -f "$secret_tmp" "$secret_dir/openai-api-key"
    trap - 0
elif [ -n "${CODEXIFY_TUNNEL_API_KEY_FILE:-}" ]; then
    fail 'CODEXIFY_TUNNEL_API_KEY_FILE does not exist.'
fi

case "${1:-}" in
    config|doctor|projects|chat) exec codexify "$@" ;;
esac

# Keep the server, authentication guard, and health check on the same config.
# In particular, --config and --api-key must not bypass the startup guard.
for argument do
    case "$argument" in
        -v|--verbose|--log-tool-calls) ;;
        *) fail 'Set server options in CODEXIFY_CONFIG; only verbosity flags are accepted at startup.' ;;
    esac
done

[ -f "$CODEXIFY_CONFIG" ] || fail "Mount a configuration at $CODEXIFY_CONFIG; see docs/DOCKER.md."
# Full schema and tunnel validation stays in Rust. Never silently start the
# native CLI's otherwise-legal unauthenticated HTTP default in a deployment.
jq -e '
    type == "object" and (
        (.apiKey | type == "string" and test("[^[:space:]]")) or
        (.openaiTunnels | type == "array" and length > 0)
    )
' "$CODEXIFY_CONFIG" >/dev/null || fail 'Configure openaiTunnels or a non-empty apiKey before starting.'

exec codexify "$@"
