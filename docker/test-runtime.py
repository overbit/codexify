"""Runtime wrapper tests; no Docker daemon or live OpenAI credentials required."""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codexify container ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.json"
        self.secret = self.root / "source-secret"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        command = self.bin / "codexify"
        command.write_text('#!/bin/sh\nprintf "CODEXIFY_CALLED\\n"\nprintf "%s\\n" "$@"\n')
        command.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.root), TMPDIR=str(self.root),
                        CODEXIFY_CONFIG=str(self.config),
                        CODEXIFY_TUNNEL_API_KEY_FILE=str(self.secret),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.secret.write_text("sk-test-secret\n")
        self.config.write_text(json.dumps({"apiKey": "test-token"}))

    def run_entrypoint(self, *args):
        return subprocess.run(["sh", str(ROOT / "entrypoint.sh"), *args],
                              env=self.env, text=True, capture_output=True)

    def test_help_does_not_require_configuration_or_secrets(self):
        self.config.unlink()
        self.secret.unlink()
        result = self.run_entrypoint("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--help", result.stdout)

    def test_missing_configuration_fails(self):
        self.config.unlink()
        result = self.run_entrypoint()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CODEXIFY_CALLED", result.stdout)

    def test_unauthenticated_or_invalid_configuration_fails(self):
        for value in ({}, {"apiKey": ""}, {"openaiTunnels": []}, [], None):
            with self.subTest(value=value):
                self.config.write_text(json.dumps(value))
                result = self.run_entrypoint()
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("CODEXIFY_CALLED", result.stdout)
        self.config.write_text("not json")
        self.assertNotEqual(self.run_entrypoint().returncode, 0)

    def test_authenticated_http_starts_without_tunnel_secret(self):
        self.secret.unlink()
        self.env.pop("CODEXIFY_TUNNEL_API_KEY_FILE")
        result = self.run_entrypoint()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CODEXIFY_CALLED", result.stdout)

    def test_native_tunnel_configuration_is_accepted(self):
        self.config.write_text(json.dumps({"openaiTunnels": [{
            "tunnelId": "tunnel_" + "a" * 32,
            "apiKeyRef": "file:/tmp/codexify-secrets/openai-api-key",
        }]}))
        result = self.run_entrypoint()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_secret_is_private_and_never_logged(self):
        self.secret.chmod(0o444)
        result = self.run_entrypoint("--verbose")
        self.assertEqual(result.returncode, 0, result.stderr)
        directory = self.root / "codexify-secrets"
        key = directory / "openai-api-key"
        self.assertEqual(key.read_bytes(), self.secret.read_bytes())
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        self.assertNotIn("sk-test-secret", result.stdout + result.stderr)
        self.assertIn("--verbose", result.stdout)
        self.secret.chmod(0o600)
        self.secret.write_text("sk-rotated-secret\n")
        self.assertEqual(self.run_entrypoint().returncode, 0)
        self.assertEqual(key.read_bytes(), self.secret.read_bytes())
        self.assertEqual(list(directory.iterdir()), [key])

    def test_missing_explicit_secret_fails(self):
        self.secret.unlink()
        result = self.run_entrypoint()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CODEXIFY_CALLED", result.stdout)

    def test_secret_directory_symlink_is_rejected(self):
        (self.root / "codexify-secrets").symlink_to(self.bin, target_is_directory=True)
        self.assertNotEqual(self.run_entrypoint().returncode, 0)
        self.assertFalse((self.bin / "openai-api-key").exists())

    def test_native_installation_commands_are_rejected(self):
        for command in ("quickstart", "service", "update", "browser"):
            with self.subTest(command=command):
                self.assertNotEqual(self.run_entrypoint(command).returncode, 0)

    def test_configuration_commands_remain_available(self):
        self.config.write_text("{}")
        result = self.run_entrypoint("config", "validate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validate", result.stdout)

    def test_healthcheck_uses_configured_port_and_ignores_proxies(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/health" else 404)
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.config.write_text(json.dumps({"port": server.server_port}))
        self.env.update(http_proxy="http://127.0.0.1:1", ALL_PROXY="http://127.0.0.1:1")
        result = subprocess.run(["sh", str(ROOT / "healthcheck.sh")], env=self.env,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"status":"ok"', result.stdout)

    def test_healthcheck_rejects_invalid_ports(self):
        for port in (0, 65536, "3000/other", 3.5):
            with self.subTest(port=port):
                self.config.write_text(json.dumps({"port": port}))
                result = subprocess.run(["sh", str(ROOT / "healthcheck.sh")], env=self.env,
                                        text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
