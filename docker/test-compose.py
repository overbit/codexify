"""Verify host-home defaults via the real Docker Compose interpolation engine."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parent.parent


class HomePathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codexify-compose-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "host home with spaces"
        self.home.mkdir()
        self.env = os.environ.copy()
        for variable in (
            "HOME", "CODEXIFY_STATE_DIR", "CODEXIFY_WORKSPACE",
            "CODEXIFY_TUNNEL_KEY_PATH", "COMPOSE_FILE", "COMPOSE_ENV_FILES",
        ):
            self.env.pop(variable, None)
        self.env["HOME"] = str(self.home)

    def compose(self, env=None):
        return subprocess.run(
            ["docker", "compose", "--env-file", "/dev/null", "-f",
             str(REPO / "compose.yaml"), "config", "--format", "json"],
            cwd=REPO, env=self.env if env is None else env,
            capture_output=True, text=True, timeout=30,
        )

    def check_paths(self, actual, state, workspace, secret):
        service = actual["services"]["codexify"]
        volumes = {mount["target"]: mount["source"] for mount in service["volumes"]}
        self.assertEqual(volumes["/home/codexify"], str(state))
        self.assertEqual(volumes["/workspace"], str(workspace))
        self.assertEqual(actual["secrets"]["openai_tunnel_api_key"]["file"], str(secret))
        self.assertNotIn(str(self.home), volumes.values())  # Never mount the whole home.
        self.assertTrue(all(mount.get("bind", {}).get("create_host_path") is False
                            for mount in service["volumes"]))

    def test_defaults_are_under_host_home(self):
        result = self.compose()
        self.assertEqual(result.returncode, 0, result.stderr)
        root = self.home / ".codexify" / "docker"
        self.check_paths(
            json.loads(result.stdout),
            root / "home", root / "workspace",
            root / "secrets" / "openai_tunnel_api_key",
        )

    def test_absolute_overrides_remain_supported(self):
        env = self.env.copy()
        env.update({
            "CODEXIFY_STATE_DIR": str(self.home / "other state"),
            "CODEXIFY_WORKSPACE": str(self.home / "other projects"),
            "CODEXIFY_TUNNEL_KEY_PATH": str(self.home / "other key"),
        })
        result = self.compose(env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.check_paths(
            json.loads(result.stdout),
            self.home / "other state",
            self.home / "other projects",
            self.home / "other key",
        )

    def test_missing_host_home_fails_closed(self):
        env = self.env.copy()
        env.pop("HOME")
        result = self.compose(env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HOME", result.stderr)


if __name__ == "__main__":
    unittest.main()
