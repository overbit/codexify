"""Exercise clone-free setup in the real image, offline with synthetic credentials."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

TUNNEL_ID = "tunnel_" + "a" * 32
KEY = "sk-synthetic-bootstrap-image-key"
CONFIG = "/home/codexify/.codexify/codexify.config.json"


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=90)
    if check and result.returncode:
        raise AssertionError(f"Docker failed ({result.returncode}): {result.stdout}{result.stderr}")
    return result


def main(image):
    prefix = "codexify-bootstrap-" + uuid.uuid4().hex[:12]
    home, workspace = prefix + "-home", prefix + "-workspace"
    base = ["run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--pids-limit", "256", "--memory", "512m",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
            "--mount", f"type=volume,src={home},dst=/home/codexify",
            "--mount", f"type=volume,src={workspace},dst=/workspace"]

    def validate(*options, tunnel=TUNNEL_ID, key=KEY, check=True):
        args = [*base, "-e", f"CODEXIFY_TUNNEL_ID={tunnel}", *options]
        if key is not None:
            args += ["-e", f"CODEXIFY_TUNNEL_API_KEY={key}"]
        return docker(*args, image, "config", "validate", check=check)

    def read_config():
        return docker(*base, "--entrypoint", "cat", image, CONFIG).stdout

    try:
        # No host directories, JSON file, .env, or pre-created volumes.
        validate()
        initial = read_config()
        config = json.loads(initial)
        assert config["openaiTunnels"][0] == {
            "tunnelId": TUNNEL_ID,
            "apiKeyRef": "file:/tmp/codexify-secrets/openai-api-key",
            "clientPath": "/usr/local/bin/tunnel-client-runtime",
        }, config
        assert KEY not in initial
        assert config["workDir"] == "/workspace"
        assert config["agentChat"]["enabled"] is False
        docker(*base, "--entrypoint", "sh", image, "-ec", """
            test "$(id -u)" = 1000
            test "$(stat -c %a "$CODEXIFY_CONFIG")" = 600
            printf persisted > /workspace/bootstrap-check
            printf persisted > /home/codexify/bootstrap-check
        """)
        print("PASS: single-command bootstrap with automatically created non-root volumes")

        # Each run replaces the container and its tmpfs; only named volumes persist.
        validate(key="sk-rotated-synthetic-key")
        assert read_config() == initial
        docker(*base, "--entrypoint", "sh", image, "-ec", """
            test "$(cat /workspace/bootstrap-check)" = persisted
            test "$(cat /home/codexify/bootstrap-check)" = persisted
        """)
        print("PASS: container replacement and key rotation preserve configuration and projects")

        assert validate(key=None, check=False).returncode != 0
        assert validate(key="", check=False).returncode != 0
        assert validate(tunnel="invalid", check=False).returncode != 0
        assert validate(tunnel="tunnel_" + "b" * 32, check=False).returncode != 0
        assert read_config() == initial
        print("PASS: missing credentials and mismatched tunnel configuration fail closed")

        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "runtime-key"
            secret.write_text(KEY + "\n")
            secret.chmod(0o444)
            mount = f"type=bind,src={secret},dst=/run/secrets/runtime-key,readonly"
            validate("--mount", mount, "-e",
                     "CODEXIFY_TUNNEL_API_KEY_FILE=/run/secrets/runtime-key", key=None)
            assert read_config() == initial
            assert validate("--mount", mount, "-e",
                            "CODEXIFY_TUNNEL_API_KEY_FILE=/run/secrets/runtime-key",
                            check=False).returncode != 0
        print("PASS: file-mounted credentials work without environment secrets")
    finally:
        docker("volume", "rm", home, workspace, check=False)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 docker/test-bootstrap-image.py IMAGE")
    main(sys.argv[1])
