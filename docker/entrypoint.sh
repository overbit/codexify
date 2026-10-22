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
    config|doctor|projects|chat) ;;
    *)
        # One configuration source keeps startup checks and health probes aligned.
        # In particular, --config/--port/--api-key must not bypass the checked file.
        for arg in "$@"; do
            case "$arg" in
                -v|-vv|-vvv|--verbose) ;;
                *) fail 'Use the JSON configuration for server options; only -v/--verbose, config, doctor, projects, chat, and --help are supported.' ;;
            esac
        done ;;
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

[ -f "$CODEXIFY_CONFIG" ] || fail "Mount a configuration at $CODEXIFY_CONFIG; see docs/DOCKER.md."
# A missing config is legal for the native CLI, but must not silently start an
# unauthenticated HTTP server in a deployment image. Full validation stays in Rust.
jq -e '
    type == "object" and (
        (.apiKey | type == "string" and test("\\S")) or
        (.openaiTunnels | type == "array" and length > 0)
    )
' "$CODEXIFY_CONFIG" >/dev/null || fail 'Configure openaiTunnels or a non-empty apiKey before starting.'

exec codexify "$@"
