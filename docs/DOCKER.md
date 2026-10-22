# Docker deployment

Use Docker Engine or Docker Desktop in Linux-container mode. No Git checkout,
Compose installation, host-folder preparation, `.env`, JSON editing, Rust, or
native Codexify installation is needed. The image supports AMD64 and ARM64.

You still need an OpenAI Secure MCP Tunnel and its scoped runtime API key, plus
ChatGPT access to custom MCP apps. Follow the [manual tunnel setup](REFERENCE.md#manual-native-openai-tunnel-setup)
to create the tunnel/key and connect ChatGPT to that tunnel. Docker replaces the
local installation steps, not OpenAI account provisioning or connector setup.

## Start

Use the [README quickstart](../README.md#docker-headless-mcp-server), the single
installation command. Only the tunnel ID and runtime key need changing.
An inline key is convenient but can remain in shell history and Docker metadata;
the [credential alternatives](#credential-alternatives) below avoid history
exposure, and a file mount also avoids storing it in Docker's configured environment.

Docker pulls the image if missing and creates both named volumes. The non-root entrypoint
creates `/home/codexify/.codexify/codexify.config.json` from the packaged headless
configuration, then starts the bundled tunnel runtime and MCP service. No ports
are published. Agent chat, browser automation, imported Codex MCP configuration,
and project setup scripts remain disabled in the packaged defaults.

PRs do not publish images. Successful main-branch Container builds publish
`ghcr.io/overbit/codexify:latest` and `sha-<full-commit-sha>`; version tags publish
their version without moving `latest`. Changes require the corresponding
published image. Pin a reviewed image digest for controlled upgrades.

Check startup without printing credentials:

```sh
docker logs --tail=100 codexify
docker inspect --format '{{.State.Health.Status}}' codexify
docker exec codexify codexify doctor
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
The README command makes `/tmp` memory-backed. The key is not written to the
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

For advanced settings, edit the generated JSON or select a mounted configuration
with `CODEXIFY_CONFIG`. Omit `CODEXIFY_TUNNEL_ID` when using a manual configuration.
Missing configuration or missing/blank bootstrap credentials fail closed.

For host-accessible projects, replace the workspace named-volume option with a
bind mount to a **dedicated existing directory**. Its ownership must allow the
container user to write. Do not mount your entire home or Docker socket. Custom
UID/GID values also require appropriately owned state storage; they are not an
automatic ownership-conversion mechanism.

The earlier repository-provided Compose file, `.env` example, and separate
Compose guide have been removed in favor of the README command. Keep your own
Compose file before updating an old checkout if you still use that deployment.
The image still accepts existing JSON configurations and file-secret mounts;
no data is moved or deleted. To reuse the earlier host-home directories, replace
the named-volume options with bind mounts of `$HOME/.codexify/docker/home` to
`/home/codexify` and `$HOME/.codexify/docker/workspace` to `/workspace`.
Use `--mount type=bind,src=...,dst=...` so a missing source fails instead of
being created as root. New named volumes do not import existing data.

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
docker pull ghcr.io/overbit/codexify:latest
```

Repeat the README command after pulling, using the same volume names.
Environment changes need container recreation; a simple restart keeps the old Docker environment.
Recreate after file-key rotation too. A rollback after a schema migration may
require the matching state backup. Do not use native `quickstart`, `service`,
`browser`, or `update` commands in the image.

## Security and scope

The image runs non-root; the command retains read-only root, dropped
capabilities, no-new-privileges, memory/process limits, and no inbound ports.
Docker's `local` log driver rotates and compresses logs automatically (100 MB
before compression by default), replacing two manual log-size options.
The quickstart no longer imposes a CPU quota or forces a pull on every creation;
add a CPU limit when needed and pull explicitly for upgrades.
These runtime restrictions come from the command flags, not from the image
alone. Keep Docker's default seccomp/AppArmor protections. Only selected volumes
are exposed to the application, not the host OS home.

This remains a headless coding service, not a hostile-code or multi-tenant
sandbox. Agent commands can modify mounted repositories/configuration, read
same-user credentials, and access outbound networks (including reachable LAN
or cloud metadata endpoints). Use scoped keys and separate trust domains;
use a dedicated VM/host for untrusted projects. Persistent volumes can still
exhaust host disk. Do not publish an unauthenticated coding endpoint.

## Included tools and extensions

The image includes the MCP server, checksum-verified tunnel runtime, Git, GitHub
CLI (`gh`), Bash, SSH client, ripgrep, curl, jq, certificates, and Tini. GitHub CLI
availability does not authenticate a GitHub account. No host credentials are
imported automatically. The desktop/browser companion and arbitrary project
language toolchains are not bundled.

Add project dependencies in a derived image, not at container startup:

```dockerfile
FROM ghcr.io/overbit/codexify:latest
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
USER 1000:1000
```

Select that image in the README command and retain its runtime restrictions.
See Docker's [volumes](https://docs.docker.com/engine/storage/volumes/) and
[local logging](https://docs.docker.com/engine/logging/drivers/local/) documentation.

## Build and test (contributors)

From a source checkout with Python 3, jq, curl, ShellCheck, and Docker:

```sh
shellcheck docker/*.sh
python3 docker/test-runtime.py -v
python3 docker/test-bootstrap.py -v
docker build -t codexify:test .
python3 docker/test-image.py codexify:test
python3 docker/test-bootstrap-image.py codexify:test
```

CI runs the image tests on AMD64 and ARM64 without network access or real
credentials, including Doctor's GitHub CLI check. It does not verify live tunnel
authentication. Builds use `cargo build --locked` and include SBOM/provenance
on publication, but mutable base tags do not provide bit-for-bit reproducibility.
