"""Exercise the real image without network access or OpenAI credentials."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, capture_output=True,
                          text=True, timeout=90)


def main(image):
    prefix = "codexify-smoke-" + uuid.uuid4().hex[:12]
    home, workspace = prefix + "-home", prefix + "-workspace"
    container = prefix
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        root.chmod(0o755)
        config = json.loads((Path(__file__).parent / "codexify.config.json").read_text())
        config.pop("openaiTunnels")
        config["apiKey"] = "container-smoke-only"
        (root / "codexify.config.json").write_text(json.dumps(config))
        (root / "codexify.config.json").chmod(0o644)
        secret = root / "secret"
        secret.write_text("sk-container-smoke-only\n")
        secret.chmod(0o444)
        try:
            assert docker("run", "--rm", "--network", "none", image, "--help").returncode == 0
            assert docker("run", "--rm", "--network", "none", image, check=False).returncode != 0
            version = docker("run", "--rm", "--network", "none", "--entrypoint",
                             "/usr/local/bin/tunnel-client-runtime", image, "--version")
            assert "0.0.12" in version.stdout + version.stderr
            docker("volume", "create", home)
            docker("volume", "create", workspace)
            docker("run", "-d", "--name", container, "--network", "none", "--read-only",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                   "--pids-limit", "256", "--memory", "512m",
                   "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
                   "--mount", f"type=volume,source={home},target=/home/codexify",
                   "--mount", f"type=volume,source={workspace},target=/workspace",
                   "--mount", f"type=bind,source={root},target=/config,readonly",
                   "--mount", f"type=bind,source={secret},target=/run/secrets/openai_tunnel_api_key,readonly",
                   "-e", "CODEXIFY_CONFIG=/config/codexify.config.json", image)

            def wait_healthy():
                for _ in range(60):
                    if docker("exec", container, "codexify-healthcheck", check=False).returncode == 0:
                        return
                    time.sleep(1)
                raise AssertionError("Container did not become healthy")

            wait_healthy()
            print("PASS: startup and bundled tunnel runtime work without network access")
            assert docker("exec", container, "id", "-u").stdout.strip() == "1000"
            docker("exec", container, "sh", "-ec", """
                grep -Eq '^CapEff:[[:space:]]+0+$' /proc/self/status
                grep -Eq '^NoNewPrivs:[[:space:]]+1$' /proc/self/status
                test ! -S /var/run/docker.sock
                ! touch /usr/local/bin/must-not-be-writable
                test "$(stat -c %a /tmp/codexify-secrets/openai-api-key)" = 600
                test "$(stat -c %a /tmp/codexify-secrets)" = 700
                printf persisted > /home/codexify/persistence-check
                mkdir -p /workspace/smoke
                printf persisted > /workspace/smoke/persistence-check
                git -C /workspace/smoke init
                git -C /workspace/smoke -c user.name=Smoke -c user.email=smoke@example.invalid commit --allow-empty -m test
            """)
            print("PASS: non-root identity, dropped capabilities, read-only root, private secret, writable projects")
            status = docker("exec", container, "curl", "--silent", "--noproxy", "*",
                            "--output", "/dev/null", "--write-out", "%{http_code}",
                            "http://127.0.0.1:3000/mcp").stdout
            assert status == "401", status

            session = None
            protocol = None

            def rpc(method, params=None, request_id=None):
                payload = {"jsonrpc": "2.0", "method": method}
                if params is not None:
                    payload["params"] = params
                if request_id is not None:
                    payload["id"] = request_id
                args = ["exec", container, "curl", "--fail", "--silent", "--show-error",
                        "--noproxy", "*", "--max-time", "10", "-D", "/tmp/mcp-headers",
                        "-H", "Authorization: Bearer container-smoke-only",
                        "-H", "Content-Type: application/json",
                        "-H", "Accept: application/json, text/event-stream"]
                if session:
                    args += ["-H", f"Mcp-Session-Id: {session}"]
                if protocol:
                    args += ["-H", f"MCP-Protocol-Version: {protocol}"]
                body = docker(*args, "--data", json.dumps(payload),
                              "http://127.0.0.1:3000/mcp").stdout
                if request_id is None:
                    return None
                text = body.strip()
                if not text.startswith("{"):
                    text = next(line[5:].strip() for line in body.splitlines() if line.startswith("data:"))
                result = json.loads(text)
                assert "error" not in result, result
                return result["result"]

            initialized = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                              "clientInfo": {"name": "container-smoke", "version": "1"}}, 1)
            protocol = initialized["protocolVersion"]
            headers = docker("exec", container, "cat", "/tmp/mcp-headers").stdout
            match = re.search(r"^mcp-session-id:\s*([^\r\n]+)", headers, re.I | re.M)
            session = match.group(1).strip() if match else None
            rpc("notifications/initialized")
            assert rpc("tools/list", {}, 2)["tools"]
            print("PASS: unauthenticated MCP rejected; authenticated initialization and tool discovery succeed")
            docker("stop", "--time", "20", container)
            assert docker("inspect", "--format", "{{.State.ExitCode}}", container).stdout.strip() == "0"
            docker("start", container)
            wait_healthy()
            docker("exec", container, "sh", "-ec", """
                test "$(cat /home/codexify/persistence-check)" = persisted
                test "$(cat /workspace/smoke/persistence-check)" = persisted
                git -C /workspace/smoke rev-parse --verify HEAD
            """)
            print("PASS: graceful SIGTERM and persistent home/workspace after restart")
            docker("run", "--rm", "--network", "none", "--read-only", "--user", "65532:65532",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                   "--tmpfs", "/tmp:mode=1777", "--tmpfs", "/home/codexify:uid=65532,gid=65532",
                   "--tmpfs", "/workspace:uid=65532,gid=65532",
                   "--mount", f"type=bind,source={root},target=/config,readonly",
                   "-e", "CODEXIFY_CONFIG=/config/codexify.config.json", image, "config", "validate")
            print("PASS: custom non-root UID/GID")
        except Exception:
            logs = docker("logs", container, check=False)
            print(logs.stdout + logs.stderr, file=sys.stderr)
            raise
        finally:
            docker("rm", "-f", container, check=False)
            docker("volume", "rm", home, workspace, check=False)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 docker/test-image.py IMAGE")
    main(sys.argv[1])
