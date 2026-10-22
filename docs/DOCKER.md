# Run Codexify in Docker

This deployment packages the **headless MCP server**, Git, shell tools, and the
OpenAI tunnel runtime. The tunnel connects outbound; the default deployment
publishes no ports and needs neither a public server URL nor host networking.
Images target Linux `amd64` and `arm64`, including Linux containers on Docker
Desktop. No Rust installation is needed to run a published image.

The optional Bun/Chrome browser companion is not included. Browser automation,
turn renewal, and the host desktop owner-chat dashboard are not supported by
this deployment. The sample also disables agent chat and host Codex discovery.
Core project selection, file tools, terminal commands, Git, worktrees, skills,
and embedded MCP widgets remain part of the Rust server.

## Image availability

The Docker workflow publishes `ghcr.io/overbit/codexify:edge` after successful
checks on `main`. Version tags publish versioned images and stable releases
also receive `latest`. The first image exists only after that workflow succeeds;
opening the Docker PR does not publish an image. Before the first publication,
use the local-build instructions below.

For production, replace the image in `.env` with an approved immutable digest:
`ghcr.io/overbit/codexify@sha256:<digest>`. `edge` is a moving development tag.

## Configure and run

Prerequisites: Docker Engine or Docker Desktop with Compose v2, an existing
OpenAI Secure MCP Tunnel, and its least-privilege runtime API key. Create the
tunnel and ChatGPT connector using the
[native tunnel instructions](REFERENCE.md#manual-native-openai-tunnel-setup).
Use a runtime key, not an administrative key. Do not paste credentials into the
image, Dockerfile, Compose file, command arguments, or Git.

From a checkout of this repository, run the following in **Bash as a non-root
user**. On Windows, use a WSL2 Linux filesystem for these permissions-sensitive
steps; do not assume Windows bind mounts preserve Linux ownership and modes.

```bash
umask 077
mkdir -p state/.codexify workspace secrets
chmod 700 state state/.codexify secrets
cp docker/codexify.config.json state/.codexify/codexify.config.json
cp docker/example.env .env
chmod 600 state/.codexify/codexify.config.json .env
```

Edit `.env` and set `CODEXIFY_UID` and `CODEXIFY_GID` to the numeric owner of the
state/workspace directories (`id -u` and `id -g`). The image defaults to
`1000:1000`. Keep both values nonzero. Existing repositories must be writable by
that identity; do not solve ownership errors with root or `chmod 777`.
Docker Desktop and rootless Docker can map ownership differently: verify the
actual mounted files are readable/writable by the selected container identity.

In `state/.codexify/codexify.config.json`, replace
`REPLACE_WITH_YOUR_TUNNEL_ID` with your tunnel ID. Keep `workDir` as `/workspace`
and `clientPath` as `/usr/local/bin/tunnel-client-runtime`. Paths in this JSON
refer to the container, not the host. Keep the supplied `apiKeyRef`: the wrapper
copies the mounted secret into a private temporary file with mode `0600`.

Save the runtime key without putting its value in shell history:

```bash
read -rsp 'OpenAI tunnel runtime key: ' key; printf '\n'
printf '%s\n' "$key" > secrets/openai_tunnel_api_key
chmod 600 secrets/openai_tunnel_api_key
unset key

docker compose pull
docker compose run --rm codexify config validate
docker compose up -d
docker compose logs --tail=100 -f codexify
```

Put repositories inside `workspace/`, or change `CODEXIFY_WORKSPACE` in `.env`
to a dedicated existing project directory. Complete the connector setup in
ChatGPT and use it in an ordinary Chat conversation. There is no host HTTP port
to open for this default tunnel deployment.

The environment file contains deployment settings, not API keys:

| Setting | Default | Purpose |
| --- | --- | --- |
| `CODEXIFY_IMAGE` | `ghcr.io/overbit/codexify:edge` | Image tag or digest |
| `CODEXIFY_UID`, `CODEXIFY_GID` | `1000`, `1000` | Container process identity |
| `CODEXIFY_STATE_DIR` | `./state` | Dedicated persistent container home |
| `CODEXIFY_WORKSPACE` | `./workspace` | Projects accessible to the tools |
| `CODEXIFY_TUNNEL_KEY_PATH` | `./secrets/openai_tunnel_api_key` | Host secret file |
| `CODEXIFY_MEMORY_LIMIT` | `2g` | Container memory limit |
| `CODEXIFY_CPU_LIMIT` | `2.0` | Container CPU limit |

Paths resolve relative to `compose.yaml` unless absolute. Missing bind sources
are rejected rather than silently created as root-owned directories.

## Persistence, configuration, and updates

`state/` is mounted at `/home/codexify`, including `.codexify` state and `.codex`
worktrees. `workspace/` is mounted separately at `/workspace`. Both survive
container replacement. Back up both together; worktree links and conversation
state can reference paths in both. The secret file is separate. The writable
configuration directory allows native atomic settings updates and schema
migrations; mounting only a single read-only config file can break them.

Use the JSON configuration for server settings. The wrapper deliberately
rejects server command-line overrides such as `--config`, `--port`, and
`--api-key`, so its authentication guard and health check cannot inspect a
different configuration from the running server. `-v` and `--verbose` are
accepted. Administrative commands remain available:

```bash
docker compose run --rm codexify config validate
docker compose exec codexify config get workDir
docker compose restart codexify
```

With a custom Compose definition, `CODEXIFY_CONFIG` can select a different
mounted configuration path. `CODEXIFY_TUNNEL_API_KEY_FILE` selects the
**in-container** source secret path (not the similarly named host-path setting
in `.env`). A custom `TMPDIR` also requires adjusting the JSON key reference.
Multiple tunnels can use native `file:` references and additional explicitly
mounted private files; each must be readable by the service and have no group
or other permissions.

To update or rotate credentials, back up state, change the selected image/key,
and recreate the service:

```bash
docker compose pull
docker compose up -d --force-recreate
```

Use an older approved digest to roll back, restoring a matching state backup
when a schema migration makes that necessary. Do not use `codexify update`,
`service`, `quickstart`, or `browser` in this image. Docker manages the process;
replace the image instead of changing a running installation. `docker compose
down` stops the service without deleting these bind-mounted directories.

The image health check probes the configured local `/health` endpoint, without
using proxy environment variables. It is **HTTP liveness, not proof that the
remote connector works**. Codexify supervises tunnel readiness/restarts itself.
Compose's restart policy restarts exited processes, not merely unhealthy ones.
Inspect the logs when the local service is healthy but the connector is offline.

## Security boundary

The supplied Compose configuration runs non-root with a read-only root
filesystem, all capabilities dropped, no-new-privileges, bounded processes/CPU/
memory/logs, and a temporary `/tmp`. The image uses a minimal init process to
forward signals and reap orphaned children. Only the dedicated home, workspace,
and temporary directory are writable. No Docker socket, privileged mode,
host networking, or inbound port is required.

**This is not a hostile-code sandbox or a multi-tenant security boundary.**
Codexify intentionally executes arbitrary project commands. Those commands run
as the service user and can read its mounted credentials and modify its writable
state and repositories. Containers share the host kernel, and outbound network
access is not restricted by this Compose file. Use a separate instance and
scoped credentials per trust domain; use a stronger sandbox/VM for untrusted
code. Never mount the host root, real home directory, Docker socket, or broad
credential directories. Docker daemon access remains highly privileged.

The secret is excluded from the build context and ordinary environment
variables, but a Compose file-backed secret is not encrypted storage. Restrict
host access, keep its owner aligned with the container user, and rotate it after
suspected compromise. The in-container copy is refreshed on each start. Default
payload logging is off and audit command previews are disabled; project output
and application errors can still contain sensitive information.

## Project toolchains and optional integrations

The base image includes Bash, Git, SSH client, ripgrep, curl, jq, CA certificates,
and the two service binaries. It does not include Node, Python, Rust, compilers,
Chrome, the Codex CLI, or notification dependencies. Build a derived image with
only the project runtimes or additional MCP dependencies you need. Install them
at build time, restore `USER 1000:1000`, and retain the Compose restrictions.
Do not grant root or mount the Docker socket to run project builds.

A numeric UID override does not create a matching `/etc/passwd` entry. Tools
that require a named account, including some SSH workflows, may need a derived
image with that account. Use dedicated Git credentials/configuration rather
than mounting the host's entire `.ssh` directory. Local MCP processes run inside
the container; `localhost` does not refer to the Docker host.

The owner-chat listener is loopback-only in the application. Publishing port
3120 does not make it a supported host dashboard, and enabling browser
integration without the companion is not sufficient. These desktop features
are intentionally outside this headless deployment.

## Build and test locally

Building requires network access to Debian repositories, Cargo dependencies,
and the pinned OpenAI runtime release. At normal startup the supplied config
uses the already-packaged tunnel executable, without downloading it again.

```bash
docker build --pull -t codexify:local .
CODEXIFY_IMAGE=codexify:local docker compose run --rm codexify config validate
CODEXIFY_IMAGE=codexify:local docker compose up -d --pull never

python3 docker/test-runtime.py -v
python3 docker/test-install-tunnel.py -v
sh docker/smoke-test.sh codexify:local
```

The Python tests need `sh`, `jq`, `curl`, `unzip`, and standard core utilities.
They use mocks/local fixtures, not OpenAI credentials. The smoke test requires
a Docker daemon and a non-root invoking user. It runs the actual server with
`--network none`, checks MCP authentication/initialization, custom-port health,
non-root execution, capabilities, secret permissions, persistence across
container recreation, and graceful shutdown. It does not test a live tunnel.

The multi-stage build compiles with `cargo build --locked`. The tunnel version
and archive checksums come from `src/openai_tunnel.rs`; a changed source format
or checksum mismatch fails the build. License notices from the verified archive
are retained. The build context allowlist excludes local config, credentials,
Git history, and deployment data. Base-image tags and Debian packages can change
between builds; this is not a bit-for-bit reproducible build. Supply approved
`RUST_IMAGE`/`RUNTIME_IMAGE` digest references as build arguments when needed.

## Publication and verification

The Docker workflow builds and smoke-tests natively on both `amd64` and `arm64`.
Pull requests do not log in or publish. Only successful main/tag runs publish
multi-architecture images with SBOM and build-provenance attestations; these are
not a claim of vulnerability-free code or a separate image signature. Actions
are pinned to commit SHAs, and package-write permission is restricted to the
publication job. The existing application CI remains unchanged.

For the first fork publication, ensure Actions are enabled and GHCR permits the
workflow's `GITHUB_TOKEN` to write packages. After publication, set the package
visibility to public for unauthenticated pulls, or authenticate Docker for a
private package. A green local wrapper suite is not a substitute for successful
container builds and smoke checks on both architectures. Validate the live
tunnel with your own scoped credentials before production deployment.
