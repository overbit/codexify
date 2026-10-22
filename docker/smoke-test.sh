#!/bin/sh
# Exercise the real image offline. No OpenAI account or secret is needed.
set -eu
image=${1:-codexify:test}
name="codexify-smoke-$$"
root=$(mktemp -d)
cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then docker logs "$name" >&2 2>/dev/null || true; fi
    docker rm -f "$name" >/dev/null 2>&1 || true
    rm -rf "$root"
}
trap cleanup 0
trap 'exit 1' HUP INT TERM
mkdir -p "$root/home/.codexify" "$root/workspace"
cat > "$root/home/.codexify/codexify.config.json" <<'JSON'
{
  "schemaVersion": 1,
  "workDir": "/workspace",
  "port": 3011,
  "apiKey": "container-smoke-test-token",
  "agentChat": { "enabled": false, "automation": { "enabled": false } },
  "codexMcp": { "enabled": false }
}
JSON
printf 'sk-container-smoke-test\n' > "$root/key"
chmod 600 "$root/key"

docker run --rm --network none --entrypoint /bin/sh "$image" -ec '
    test "$(id -u)" = 1000
    test "$(id -g)" = 1000
    test ! -w /usr/local/bin/codexify
    codexify --help >/dev/null
    tunnel-client-runtime --version
    tunnel-client-runtime run --help | grep -q -- --mcp.discovery-extra-headers
    test -s /usr/share/doc/tunnel-client-runtime/LICENSE
    test -s /usr/share/doc/tunnel-client-runtime/NOTICE
'
if docker run --rm --network none "$image" > "$root/missing-config.log" 2>&1; then
    printf 'An unconfigured image must not start successfully.\n' >&2
    exit 1
fi
grep -q 'Mount a configuration' "$root/missing-config.log"

start() {
    docker run -d --name "$name" --network none \
        --user "$(id -u):$(id -g)" \
        --read-only --cap-drop ALL --security-opt no-new-privileges:true \
        --pids-limit 256 --memory 2g --cpus 2 \
        --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 \
        --mount "type=bind,src=$root/home,dst=/home/codexify" \
        --mount "type=bind,src=$root/workspace,dst=/workspace" \
        --mount "type=bind,src=$root/key,dst=/run/secrets/openai_tunnel_api_key,readonly" \
        --health-interval 1s --health-start-period 0s --health-retries 30 \
        "$image" >/dev/null
    attempts=0
    until [ "$(docker inspect --format '{{.State.Health.Status}}' "$name")" = healthy ]; do
        attempts=$((attempts + 1))
        [ "$attempts" -lt 60 ] || { printf 'Health check timed out.\n' >&2; exit 1; }
        [ "$(docker inspect --format '{{.State.Running}}' "$name")" = true ] || exit 1
        sleep 1
    done
}
start
status=$(docker exec "$name" curl --silent --noproxy '*' --output /dev/null \
    --write-out '%{http_code}' http://127.0.0.1:3011/mcp)
[ "$status" = 401 ] || { printf 'Unauthenticated MCP returned %s, expected 401.\n' "$status" >&2; exit 1; }
docker exec "$name" curl --fail --silent --show-error --noproxy '*' \
    -H 'Authorization: Bearer container-smoke-test-token' \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"docker-smoke","version":"1"}}}' \
    http://127.0.0.1:3011/mcp > "$root/initialize.json"
grep -q 'serverInfo' "$root/initialize.json"
docker exec "$name" /bin/sh -ec '
    test "$(id -u)" != 0
    touch /workspace/persisted
    touch "$HOME/.codexify/persisted"
    if touch /etc/codexify-must-not-be-writable 2>/dev/null; then exit 1; fi
    test "$(stat -c %a /tmp/codexify-secrets)" = 700
    test "$(stat -c %a /tmp/codexify-secrets/openai-api-key)" = 600
    grep -Eq "^CapEff:[[:space:]]+0+$" /proc/self/status
    grep -Eq "^NoNewPrivs:[[:space:]]+1$" /proc/self/status
'
# Recreate, rather than merely restart, to prove data is not in the image layer.
docker stop --time 30 "$name" >/dev/null
[ "$(docker inspect --format '{{.State.ExitCode}}' "$name")" = 0 ]
docker rm "$name" >/dev/null
start
docker exec "$name" /bin/sh -ec 'test -f /workspace/persisted && test -f "$HOME/.codexify/persisted"'
docker stop --time 30 "$name" >/dev/null
[ "$(docker inspect --format '{{.State.ExitCode}}' "$name")" = 0 ]
printf 'Container smoke checks passed.\n'
