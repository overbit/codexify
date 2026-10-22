#!/bin/sh
set -eu
umask 077

fail() {
    printf 'codexify container: %s\n' "$*" >&2
    exit 1
}

# Remove the convenience credential from the application's inherited environment.
# Docker still retains --env values in container metadata; prefer a file for secrets.
key_from_env="${CODEXIFY_TUNNEL_API_KEY+x}"
unset tunnel_key
tunnel_key="${CODEXIFY_TUNNEL_API_KEY:-}"
unset CODEXIFY_TUNNEL_API_KEY

export CODEXIFY_CONFIG="${CODEXIFY_CONFIG:-$HOME/.codexify/codexify.config.json}"
case "${1:-}" in
    -h|--help) exec codexify "$@" ;;
    config|doctor|projects|chat|github) ;;
    *)
        # One configuration source keeps startup checks and health probes aligned.
        # In particular, --config/--port/--api-key must not bypass the checked file.
        for arg in "$@"; do
            case "$arg" in
                -v|-vv|-vvv|--verbose) ;;
                *) fail 'Use the JSON configuration for server options; only -v/--verbose, config, doctor, github, projects, chat, and --help are supported.' ;;
            esac
        done ;;
esac

# Mounted key files can have different permissions on the host. Make a private
# copy rather than weakening Codexify's strict file-key validator.
secret_file="${CODEXIFY_TUNNEL_API_KEY_FILE:-/run/secrets/openai_tunnel_api_key}"
secret_dir="${TMPDIR:-/tmp}/codexify-secrets"
secret_ready=false
if [ -n "$key_from_env" ] && { [ -n "${CODEXIFY_TUNNEL_API_KEY_FILE+x}" ] || [ -e "$secret_file" ]; }; then
    fail 'Provide either CODEXIFY_TUNNEL_API_KEY or a tunnel secret file, not both.'
fi
if [ -n "$key_from_env" ] || [ -e "$secret_file" ]; then
    if [ -z "$key_from_env" ] && { [ ! -f "$secret_file" ] || [ ! -r "$secret_file" ]; }; then
        fail 'Tunnel secret must be a readable regular file.'
    fi
    [ ! -L "$secret_dir" ] || fail 'Private secret directory must not be a symlink.'
    mkdir -p "$secret_dir"
    chmod 700 "$secret_dir"
    secret_tmp=$(mktemp "$secret_dir/key.XXXXXX")
    trap 'rm -f "$secret_tmp"' 0
    if [ -n "$key_from_env" ]; then
        printf '%s\n' "$tunnel_key" > "$secret_tmp"
    else
        cat "$secret_file" > "$secret_tmp"
    fi
    unset tunnel_key
    LC_ALL=C grep -q '[^[:space:]]' "$secret_tmp" || fail 'Tunnel runtime key must not be empty.'
    mv -f "$secret_tmp" "$secret_dir/openai-api-key"
    trap - 0
    secret_ready=true
elif [ -n "${CODEXIFY_TUNNEL_API_KEY_FILE:-}" ]; then
    fail 'CODEXIFY_TUNNEL_API_KEY_FILE does not exist.'
fi
unset tunnel_key

# Bootstrap only: never replace persisted user settings or a mounted JSON config.
if [ -n "${CODEXIFY_TUNNEL_ID+x}" ]; then
    jq -en --arg id "$CODEXIFY_TUNNEL_ID" \
        '$id | length == 39 and test("^tunnel_[a-z0-9]{32}$")' >/dev/null \
        || fail 'CODEXIFY_TUNNEL_ID must be tunnel_ followed by 32 lowercase letters or digits.'
    [ "$secret_ready" = true ] || fail 'Provide CODEXIFY_TUNNEL_API_KEY or mount a tunnel runtime key file.'
    [ ! -L "$CODEXIFY_CONFIG" ] || fail 'Bootstrap configuration must not be a symlink.'
    key_ref="file:$secret_dir/openai-api-key"
    if [ -e "$CODEXIFY_CONFIG" ]; then
        jq -e --arg id "$CODEXIFY_TUNNEL_ID" --arg key_ref "$key_ref" '
            type == "object" and
            (.openaiTunnels | type == "array" and length == 1) and
            .openaiTunnels[0].tunnelId == $id and
            .openaiTunnels[0].apiKeyRef == $key_ref
        ' "$CODEXIFY_CONFIG" >/dev/null || fail 'Existing configuration does not match the requested tunnel/key path. Edit it explicitly or use a new state volume; it has not been overwritten.'
    else
        config_dir=$(dirname "$CODEXIFY_CONFIG")
        mkdir -p "$config_dir"
        config_tmp=$(mktemp "$config_dir/config.XXXXXX")
        trap 'rm -f "$config_tmp"' 0
        jq --arg id "$CODEXIFY_TUNNEL_ID" --arg key_ref "$key_ref" '
            .openaiTunnels[0].tunnelId = $id |
            .openaiTunnels[0].apiKeyRef = $key_ref
        ' "${CODEXIFY_CONFIG_TEMPLATE:-/etc/codexify/codexify.config.json}" > "$config_tmp"
        mv -f "$config_tmp" "$CODEXIFY_CONFIG"
        trap - 0
        printf 'codexify container: created configuration at %s\n' "$CODEXIFY_CONFIG"
    fi
fi

case "${1:-}" in
    config|doctor|projects|chat|github) exec codexify "$@" ;;
esac

[ -f "$CODEXIFY_CONFIG" ] || fail "Set CODEXIFY_TUNNEL_ID and provide a runtime key, or mount a configuration at $CODEXIFY_CONFIG; see docs/DOCKER.md."
# A missing config is legal for the native CLI, but must not silently start an
# unauthenticated HTTP server in a deployment image. Full validation stays in Rust.
jq -e '
    type == "object" and (
        (.apiKey | type == "string" and test("\\S")) or
        (.openaiTunnels | type == "array" and length > 0)
    )
' "$CODEXIFY_CONFIG" >/dev/null || fail 'Configure openaiTunnels or a non-empty apiKey before starting.'

exec codexify "$@"
