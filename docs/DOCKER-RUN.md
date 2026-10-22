# Run Codexify with one Docker command

Use Docker Engine or Docker Desktop in Linux-container mode. No Git checkout,
Compose installation, host-folder preparation, `.env`, JSON editing, Rust, or
native Codexify installation is needed. The image supports AMD64 and ARM64.

You still need an OpenAI Secure MCP Tunnel and its scoped runtime API key, plus
ChatGPT access to custom MCP apps. Follow the [manual tunnel setup](REFERENCE.md#manual-native-openai-tunnel-setup)
to create the tunnel/key and connect ChatGPT to that tunnel. Docker replaces the
local installation steps, not OpenAI account provisioning or connector setup.

## Start

Replace the two placeholder values below. This convenience example passes the
key through an environment variable: Docker stores it in container metadata,
and a literal key entered here can remain in shell history. The
[credential alternatives](#credential-alternatives) avoid putting the literal
key in your command history; a file mount also avoids storing it in Docker's
configured environment.

```sh
docker run -d --name codexify --restart unless-stopped --pull=always \
  --env CODEXIFY_TUNNEL_ID='REPLACE_WITH_YOUR_TUNNEL_ID' \
  --env CODEXIFY_TUNNEL_API_KEY='REPLACE_WITH_YOUR_RUNTIME_KEY' \
  --mount type=volume,src=codexify-home,dst=/home/codexify \
  --mount type=volume,src=codexify-workspace,dst=/workspace \
  --read-only --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --pids-limit 256 --memory 2g --cpus 2 --stop-timeout 30 \
  --log-opt max-size=10m --log-opt max-file=3 \
  ghcr.io/overbit/codexify:latest
```

Docker pulls the image and creates both named volumes. The non-root entrypoint
creates `/home/codexify/.codexify/codexify.config.json` from the packaged headless
configuration, then starts the bundled tunnel runtime and MCP service. No ports
are published. Agent chat, browser automation, imported Codex MCP configuration,
and project setup scripts remain disabled in the packaged defaults.

This requires an image containing the single-command bootstrap feature. PRs do
not publish images; a successful main-branch Container workflow publishes
`latest`. Until that publication, an older `latest` does not recognize these
bootstrap inputs. A `sha-<full-commit-sha>` tag or reviewed image digest can be
used instead of `latest` for a controlled deployment.

Check startup without printing credentials:

```sh
docker logs --tail=100 codexify
docker inspect --format '{{.State.Health.Status}}' codexify
```

Tunnel connection can take time; the health check has a startup grace period.
It reflects application/tunnel readiness, not a complete ChatGPT connection
test. Select the tunnel in your ChatGPT connector and begin with a read-only
project inspection. The workspace is `/workspace` inside the container; clone
or create intended projects there using Codexify's tools.

## Credential alternatives

**Prompt without storing the literal key in shell history (Bash or Zsh).**

```sh
printf 'Tunnel runtime API key: '
IFS= read -rs CODEXIFY_TUNNEL_API_KEY && export CODEXIFY_TUNNEL_API_KEY
printf '\n'
```

In the `docker run` command, replace the key line with
`--env CODEXIFY_TUNNEL_API_KEY` (no `=value`). After running it, use
`unset CODEXIFY_TUNNEL_API_KEY` in the host shell. Docker metadata still contains
the supplied environment value. The wrapper removes it from the environment
inherited by Codexify, but cannot remove Docker's stored configuration.

**Use an existing key file instead.** Replace the key environment line with:

```sh
  --mount type=bind,src="$HOME/.codexify/docker/secrets/openai_tunnel_api_key",dst=/run/secrets/openai_tunnel_api_key,readonly \
```

The source file must exist and be readable by the container user (UID/GID
`1000:1000` by default). For a different in-container path, set
`CODEXIFY_TUNNEL_API_KEY_FILE` to that path. Do not supply an environment key
and a key file together; ambiguous sources are rejected. File-mounted keys
remain the recommended option for persistent deployments.

Both modes copy the key to a `0600` file in a `0700` directory under `/tmp`.
The command above makes `/tmp` memory-backed. The key is not written to the
JSON configuration or the persistent home. Commands executed by the service
user can nevertheless read the same-user key file; this is not secret isolation
from the coding agent.

## Persistence and configuration

`codexify-home` stores configuration/settings; `codexify-workspace` stores
projects. They are Docker-managed volumes, not folders relative to your current
directory. They survive container removal. Back up both; do not delete them
with `docker volume rm` or prune volumes that you still need. Use different
container and volume names for separate installations. Do not run two servers
against the same state volume concurrently.

The configuration is generated **only when missing**. On later starts, the
same tunnel ID/key-file reference must match the stored configuration; other
settings are preserved byte-for-byte by the wrapper. Native schema migrations
still apply. A different tunnel ID or conflicting existing manual configuration
fails with an explicit error rather than silently replacing settings. Edit
that configuration deliberately or use a separate state volume.

`CODEXIFY_CONFIG` continues to select an advanced configuration path.
`CODEXIFY_CONFIG_TEMPLATE` optionally selects a different first-start template
for derived images; it defaults to the bundled `/etc/codexify/codexify.config.json`.
Without `CODEXIFY_TUNNEL_ID`, the existing manual-JSON behavior is unchanged.
Missing configuration or missing/blank bootstrap credentials fail closed.

For host-accessible projects, replace the workspace named-volume option with a
bind mount to a **dedicated existing directory**. Its ownership must allow the
container user to write. Do not mount your entire home or Docker socket. Custom
UID/GID values also require appropriately owned state storage; they are not an
automatic ownership-conversion mechanism.

Existing Compose installations do not need migration. Their
`$HOME/.codexify/docker/...` paths, file secrets, `.env` overrides, and manual
configuration remain supported. See [advanced Compose deployment](DOCKER.md)
for that workflow, permissions, and migration from older checkout-relative
folders. New named volumes do not automatically import existing host-folder data.

## Operations

```sh
docker stop codexify
docker start codexify
docker logs --tail=100 codexify
```

For an upgrade or key rotation, back up state/projects, record the previous
image digest, stop and remove **only the container**, then repeat the `docker run`
command with the same volume names and the new image/key:

```sh
docker stop codexify
docker rm codexify
```

The `--pull=always` option fetches the selected image. Environment changes need
container recreation; a simple restart keeps the old Docker environment.
Recreate after file-key rotation too. A rollback after a schema migration may
require the matching state backup. Do not use native `quickstart`, `service`,
`browser`, or `update` commands in the image.

## Security and scope

The image runs non-root; the command retains read-only root, dropped
capabilities, no-new-privileges, bounded resources/logs, and no inbound ports.
These runtime restrictions come from the command flags, not from the image
alone. Keep Docker's default seccomp/AppArmor protections. Only selected volumes
are exposed to the application, not the host OS home.

This remains a headless coding service, not a hostile-code or multi-tenant
sandbox. Agent commands can modify mounted repositories/configuration, read
same-user credentials, and access outbound networks (including reachable LAN
or cloud metadata endpoints). Use scoped keys and separate trust domains;
use a dedicated VM/host for untrusted projects. Persistent volumes can still
exhaust host disk. Do not publish an unauthenticated coding endpoint.

The desktop/browser companion and arbitrary language toolchains are not bundled.
See the [derived-image instructions](DOCKER.md#supported-scope-and-project-dependencies)
for adding project dependencies. See [Docker's volume documentation](https://docs.docker.com/engine/storage/volumes/)
and [secret-handling guidance](https://docs.docker.com/compose/how-tos/use-secrets/)
for Docker's storage and credential boundaries.
