# Docker deployment

Run the headless Codexify MCP server using a Linux container. Docker supervises the process; the host does not need Rust, Bun, Codex CLI, or a native Codexify installation. ChatGPT performs the reasoning and Codexify executes tools inside the container.

The default deployment uses an outbound OpenAI Secure MCP Tunnel and publishes **no host ports**. The image includes the tunnel runtime, verified against the version and SHA-256 hashes pinned in `src/openai_tunnel.rs`. The supplied configuration uses that bundled executable rather than downloading it at startup.

## Images and prerequisites

Use Docker Engine with Compose v2, or Docker Desktop in Linux-container mode. Images target `linux/amd64` and `linux/arm64`. On Windows, run the permission-sensitive shell examples from a WSL Linux filesystem. On Docker Desktop, make the selected project directory accessible to Docker.

The Container workflow builds and tests both architectures. Successful `main` runs publish `ghcr.io/overbit/codexify:latest` and `sha-<full-commit-sha>`. A `v*` tag publishes its version without the `v` prefix and a SHA tag, without moving `latest`. **Images become available only after a successful publishing run; pull requests do not publish.**

Before the first publication, build the checked-out PR locally:

```sh
docker build -t codexify:local .
# Set CODEXIFY_IMAGE=codexify:local in .env below.
```

For another fork, the workflow derives the image name from that repository. Set `CODEXIFY_IMAGE` accordingly. Maintainers must enable Actions and permit package writes. The GHCR package may need its visibility changed to public for anonymous pulls; a public repository does not automatically guarantee public package access.

## Configure and start

From a checkout, or a deployment directory containing `compose.yaml`, `docker/example.env`, and `docker/codexify.config.json`, run as your normal **non-root** user. Compose uses the invoking user's **host OS `HOME`**, not the checkout directory, for all default bind mounts and the tunnel key:

```text
$HOME/.codexify/docker/
  home/       Container home, configuration, persistent state
  workspace/  Dedicated projects accessible to Codexify
  secrets/    Tunnel runtime key, mounted as a Compose secret
```

Create these folders under your home directory and copy the sample configuration:

```sh
umask 077
mkdir -p "$HOME/.codexify/docker/home/.codexify" \
         "$HOME/.codexify/docker/workspace" \
         "$HOME/.codexify/docker/secrets"
chmod 700 "$HOME/.codexify/docker" "$HOME/.codexify/docker/home" "$HOME/.codexify/docker/secrets"
cp docker/example.env .env
cp docker/codexify.config.json "$HOME/.codexify/docker/home/.codexify/codexify.config.json"
```

Edit `.env`. On ordinary Linux Docker Engine, set `CODEXIFY_UID` and `CODEXIFY_GID` to the values reported by `id -u` and `id -g`; both default to `1000`. Keep them nonzero. To use a different project directory, set `CODEXIFY_WORKSPACE` to its **absolute host path**, and mount only projects Codexify should access. The selected identity must be able to write the persistent state and workspace directories. The image does not start as root to change host ownership.

Create an OpenAI Secure MCP Tunnel and a least-privilege runtime key using the [manual native tunnel guide](REFERENCE.md#manual-native-openai-tunnel-setup). ChatGPT custom-app access and OpenAI Platform tunnel permissions are separate prerequisites. Replace `REPLACE_WITH_YOUR_TUNNEL_ID` in `$HOME/.codexify/docker/home/.codexify/codexify.config.json` with the actual ID. Leave `clientPath`, `apiKeyRef`, and `workDir` unchanged. JSON paths refer to the container, not the host.

Save the runtime key with a local editor, or use this **Bash or Zsh** prompt without echoing it or placing its value in shell history:

```bash
printf 'Tunnel runtime API key: '
IFS= read -rs tunnel_key
printf '\n'
printf '%s\n' "$tunnel_key" > "$HOME/.codexify/docker/secrets/openai_tunnel_api_key"
unset tunnel_key
chmod 600 "$HOME/.codexify/docker/secrets/openai_tunnel_api_key"
```

Do not put the key in the image, Dockerfile, `.env`, Git, command arguments, or a ChatGPT message. The host key file must be readable by the selected container UID. The deployment's `.env` remains gitignored in the checkout; state and credentials live under the host home, outside the Docker build context. The build uses an explicit allowlist.

Validate and start:

```sh
docker compose config --quiet
docker compose pull                          # Skip for a locally built image.
docker compose run --rm codexify config validate
docker compose up -d
docker compose ps
docker compose logs --tail=100 codexify
```

Finish the ChatGPT connector setup in the native tunnel guide, then test a read-only project inspection in a regular Chat conversation. The tunnel needs outbound network access, not router port forwarding or a public container endpoint.

The example disables agent chat/browser automation, host Codex CLI MCP imports, worktree setup scripts, tool payload logging, and audit command previews. Its deliberately invalid tunnel-ID placeholder prevents an unconfigured deployment from starting successfully.

## Deployment settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `CODEXIFY_IMAGE` | `ghcr.io/overbit/codexify:latest` | Image tag or immutable digest |
| `CODEXIFY_UID`, `CODEXIFY_GID` | `1000`, `1000` | Container process identity |
| `CODEXIFY_STATE_DIR` | `$HOME/.codexify/docker/home` | Dedicated persistent container home |
| `CODEXIFY_WORKSPACE` | `$HOME/.codexify/docker/workspace` | Projects accessible to the tools |
| `CODEXIFY_TUNNEL_KEY_PATH` | `$HOME/.codexify/docker/secrets/openai_tunnel_api_key` | Host secret file |
| `CODEXIFY_MEMORY_LIMIT` | `2g` | Memory limit |
| `CODEXIFY_CPU_LIMIT` | `2.0` | CPU limit |

Compose expands `HOME` from the **host shell** and rejects missing `HOME` when using default paths. Run Compose from your normal user session (not `sudo`, which may change `HOME`). For Windows, use Docker Desktop with a WSL Linux shell and its `HOME`. Optional path overrides should be absolute; existing relative overrides still resolve from the Compose project directory. Missing bind sources are rejected rather than silently created as root-owned directories.

## State, permissions, and secrets

The dedicated `$HOME/.codexify/docker/home/` directory mounts at `/home/codexify`, including `.codexify` configuration/settings and `.codex` worktree state. `$HOME/.codexify/docker/workspace/` mounts separately at `/workspace`. Both survive container replacement. Back up both together; state and worktree links can reference paths in each.

Mount the state **directory**, not only a read-only configuration file. Native settings updates and schema migrations use atomic replacement and may create adjacent backups. Never mount your actual host home as the container home. Existing linked Git worktrees containing host-absolute paths may not work; use a normal clone or create worktrees inside the container.

For permission errors, check UID/GID and directory access. Do not use `chmod 777` or recursively change ownership of unrelated projects. Rootless Docker and user-namespace remapping can map container IDs to different host IDs; provision permissions for that mapping. SELinux hosts may require an administrator-approved bind-mount labeling policy. A numeric UID override does not create an account in `/etc/passwd`; some SSH workflows need a derived image containing that account.

The Compose secret mounts read-only at `/run/secrets/openai_tunnel_api_key`. Because file-backed Compose secrets do not consistently implement ownership/mode overrides, the entrypoint copies the readable source into a private `0700` directory with a `0600` key file. This preserves Codexify's existing strict key-file validation. The copy lives in `/tmp` tmpfs, not the image or persistent home.

After replacing a credential, recreate the service to refresh the mounted source and private copy:

```sh
docker compose up -d --force-recreate codexify
```

With a custom Compose definition, `CODEXIFY_CONFIG` selects a different in-container configuration path and `CODEXIFY_TUNNEL_API_KEY_FILE` selects the in-container source secret path. The latter is different from the host-path setting `CODEXIFY_TUNNEL_KEY_PATH`. Changing `TMPDIR` also requires updating the JSON `apiKeyRef`. Additional native tunnels may use explicitly mounted private files and native `file:` references; all configured tunnels share the instance's project access.

Server options belong in JSON. The wrapper rejects `--config`, `--port`, and `--api-key` server overrides so its authentication check, health probe, and running server cannot silently use different configurations. `-v`/`--verbose` and the `config`, `doctor`, `projects`, and `chat` subcommands remain available. Supporting a command does not enable an integration disabled by the example configuration.

### Migrating an existing checkout-relative deployment

Previous examples used `./state`, `./workspace`, and `./secrets`. Any paths explicitly saved in an existing `.env` **continue to work**; this update never moves, deletes, or silently replaces their data. To switch to the home-based defaults, back up your data, stop the container, and copy the old contents:

```sh
docker compose down
umask 077
mkdir -p "$HOME/.codexify/docker/home" \
         "$HOME/.codexify/docker/workspace" \
         "$HOME/.codexify/docker/secrets"
cp -a state/. "$HOME/.codexify/docker/home/"
cp -a workspace/. "$HOME/.codexify/docker/workspace/"
cp -a secrets/openai_tunnel_api_key "$HOME/.codexify/docker/secrets/openai_tunnel_api_key"
chmod 600 "$HOME/.codexify/docker/secrets/openai_tunnel_api_key"
```

These commands assume the old paths still point to checkout-relative directories; do not copy blindly if your `.env` already uses custom paths. Remove or comment out the old `CODEXIFY_STATE_DIR`, `CODEXIFY_WORKSPACE`, and `CODEXIFY_TUNNEL_KEY_PATH` entries in `.env`, then verify with `docker compose config`, restart with `docker compose up -d`, and check your existing projects and settings. Retain the original files until the migration has been verified. Worktrees with absolute host paths may need repair.

## Security boundary

The supplied Compose configuration runs non-root with a read-only root filesystem, all Linux capabilities dropped, `no-new-privileges`, and bounded memory, CPU, process count, temporary storage, and Docker log growth. A minimal init forwards signals and reaps orphaned children. No Docker socket, host networking, host PID namespace, desktop display, or published port is required. Keep Docker's default seccomp/AppArmor protections enabled.

**This is not a hostile-code sandbox or a multi-tenant security boundary.** Codexify intentionally executes arbitrary commands as its own user. Those commands can read same-user credentials, modify writable configuration and repositories, and use outbound networking. A mounted secret keeps credentials out of image layers and ordinary environment configuration; it does not conceal them from commands running in the same container.

Use scoped credentials and separate instances for different trust domains. Never add the Docker socket, privileged mode, host networking, your entire home, or broad host credentials to make a project build work. Containers share the host kernel; use a dedicated VM/host and externally enforced egress controls for untrusted projects. The recipe does not block reachable LAN services or cloud metadata endpoints. Persistent data can exhaust host disk despite Docker log limits. File-backed secrets are not encrypted storage, and logs/project output may still contain sensitive information.

## Supported scope and project dependencies

The image provides Codexify's headless MCP tools, Git, Bash, SSH client, ripgrep, curl, jq, certificates, and the tunnel runtime. It does not include the optional desktop browser companion, browser-driven automation, standalone owner-chat interface, Node, Python/Apprise, Rust, Codex CLI, or every project's build dependencies. Publishing the loopback-only owner-chat port does not make the desktop workflow supported.

Install required project runtimes or additional stdio MCP executables in a derived image, not at container startup. For example:

```dockerfile
FROM ghcr.io/overbit/codexify:latest
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
USER 1000:1000
```

Build it, select it through `CODEXIFY_IMAGE`, and retain the Compose restrictions. Pin the base to a reviewed digest for controlled deployments. Configure dedicated Git identity/credentials in the container home rather than copying all host credentials. `localhost` in MCP configuration refers to the container, not the Docker host.

Native tunnels are the default. Advanced deployments can replace `openaiTunnels` with a strong non-empty `apiKey` and use the existing HTTP MCP transport, but must provide authenticated TLS ingress and appropriate network policy. The supplied Compose file deliberately provides no HTTP ingress. Never expose an unauthenticated coding endpoint.

## Operations and upgrades

The health check probes the configured local `/health` endpoint without proxy environment variables. This reports application readiness, including the server's supervised tunnel state in native tunnel mode; it is **not an end-to-end test of the ChatGPT connector**. Docker's `unless-stopped` restarts exited containers, not merely unhealthy ones. Inspect logs and the real connector when diagnosing connectivity.

The init process forwards Docker's SIGTERM to the application. Upstream native tunnel mode has its own shutdown handler. The HTTP-only mode used by offline smoke tests currently terminates directly on SIGTERM and normally reports exit code 143; the tests reject forced SIGKILL, out-of-memory termination, and unrelated failures. They do not establish that in-flight tool commands or a live tunnel drain gracefully.

Back up state and projects, retain the previous image digest, then update:

```sh
docker compose pull
docker compose up -d --force-recreate
docker compose ps
```

For production, select a reviewed `ghcr.io/overbit/codexify@sha256:<digest>` rather than a moving tag. Rollback may require a matching state backup after a schema migration. `docker compose down` leaves bind-mounted state and projects intact. Do not use native `quickstart`, `service`, `browser`, or `update` commands in this image; Docker manages the process and upgrades replace the image.

## Build and validation

```sh
python3 docker/test-runtime.py -v
python3 docker/test-compose.py -v
docker build -t codexify:test .
python3 docker/test-image.py codexify:test
```

The wrapper tests need Python 3, POSIX shell, jq, and curl. The Compose path tests additionally require Docker Compose v2; they check default host-home mounts, absolute overrides, and rejection of missing `HOME`. The image test requires Docker and runs without network access or real OpenAI credentials. It checks missing-configuration failure, the bundled tunnel executable, authenticated MCP initialization/tool discovery, rejected unauthenticated access, non-root identity, filesystem/capability restrictions, secret permissions, Git, persistent state after restart, SIGTERM forwarding without forced termination, and custom UID/GID configuration validation. It does not validate a live OpenAI tunnel or a browser session; verify your connector with a restricted project before production use.

The multi-stage build uses `cargo build --locked` and a versioned Rust builder. Base tags and distribution repositories remain mutable, so this is not a claim of bit-for-bit reproducibility. `RUST_IMAGE` and `RUNTIME_IMAGE` accept approved digest-pinned references. A tunnel version/hash mismatch with the Rust source fails the image build until its installer pins are updated.

Pull requests build and test without publishing. Successful trusted main/tag runs publish native architecture images, then a combined manifest, with SBOM and build-provenance attestations. These attestations are not a separate image signature or a claim that dependencies are vulnerability-free. Existing application CI remains unchanged.
