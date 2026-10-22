"""Test single-command setup without Docker or real tunnel credentials."""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
TUNNEL_ID = "tunnel_" + "a" * 32


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codexify bootstrap ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / ".codexify" / "codexify.config.json"
        self.bin = self.home / "bin"
        self.bin.mkdir()
        command = self.bin / "codexify"
        command.write_text('#!/bin/sh\n'
                           'test "${CODEXIFY_TUNNEL_API_KEY+x}" != x || exit 99\n'
                           'test "${tunnel_key+x}" != x || exit 98\n'
                           'printf "CODEXIFY_CALLED\\n"\n')
        command.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CODEXIFY_")}
        self.env.update(HOME=str(self.home), TMPDIR=str(self.home),
                        CODEXIFY_CONFIG_TEMPLATE=str(ROOT / "codexify.config.json"),
                        CODEXIFY_TUNNEL_ID=TUNNEL_ID,
                        CODEXIFY_TUNNEL_API_KEY="sk-synthetic-bootstrap-key",
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])

    def run_entrypoint(self, *args):
        return subprocess.run(["sh", str(ROOT / "entrypoint.sh"), *args],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def assert_started(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CODEXIFY_CALLED", result.stdout)

    def assert_rejected(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CODEXIFY_CALLED", result.stdout)

    def test_fresh_home_uses_packaged_defaults_without_persisting_the_key(self):
        result = self.run_entrypoint()
        self.assert_started(result)
        expected = json.loads((ROOT / "codexify.config.json").read_text())
        expected["openaiTunnels"][0].update(
            tunnelId=TUNNEL_ID,
            apiKeyRef="file:" + str(self.home / "codexify-secrets" / "openai-api-key"))
        self.assertEqual(json.loads(self.config.read_text()), expected)
        self.assertNotIn(self.env["CODEXIFY_TUNNEL_API_KEY"], self.config.read_text())
        self.assertNotIn(self.env["CODEXIFY_TUNNEL_API_KEY"], result.stdout + result.stderr)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        secret = self.home / "codexify-secrets" / "openai-api-key"
        self.assertEqual(secret.read_text(), self.env["CODEXIFY_TUNNEL_API_KEY"] + "\n")
        self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(secret.parent.stat().st_mode), 0o700)

    def test_restart_preserves_settings_and_rotates_only_the_private_key(self):
        self.assert_started(self.run_entrypoint())
        settings = json.loads(self.config.read_text())
        settings["port"] = 4321
        self.config.write_text(json.dumps(settings, indent=4) + "\n")
        saved = self.config.read_bytes()
        self.env["CODEXIFY_TUNNEL_API_KEY"] = "sk-new-synthetic-key"
        self.assert_started(self.run_entrypoint())
        self.assertEqual(self.config.read_bytes(), saved)
        self.assertEqual((self.home / "codexify-secrets" / "openai-api-key").read_text(),
                         "sk-new-synthetic-key\n")

    def test_different_tunnel_cannot_overwrite_existing_configuration(self):
        self.assert_started(self.run_entrypoint())
        saved = self.config.read_bytes()
        self.env["CODEXIFY_TUNNEL_ID"] = "tunnel_" + "b" * 32
        self.assert_rejected(self.run_entrypoint())
        self.assertEqual(self.config.read_bytes(), saved)

    def test_manual_configuration_is_not_overwritten(self):
        self.config.parent.mkdir()
        saved = '{"apiKey":"existing-http-token"}\n'
        self.config.write_text(saved)
        self.assert_rejected(self.run_entrypoint())
        self.assertEqual(self.config.read_text(), saved)
        self.env.pop("CODEXIFY_TUNNEL_ID")
        self.env.pop("CODEXIFY_TUNNEL_API_KEY")
        self.assert_started(self.run_entrypoint())
        self.assertEqual(self.config.read_text(), saved)

    def test_file_secret_bootstraps_without_environment_secret(self):
        self.env.pop("CODEXIFY_TUNNEL_API_KEY")
        source = self.home / "source key"
        source.write_text("sk-file-synthetic-key\n")
        source.chmod(0o444)
        self.env["CODEXIFY_TUNNEL_API_KEY_FILE"] = str(source)
        self.assert_started(self.run_entrypoint("config", "validate"))
        self.assertTrue(self.config.is_file())

    def test_conflicting_secret_sources_are_rejected(self):
        self.env["CODEXIFY_TUNNEL_API_KEY_FILE"] = str(self.home / "missing-file")
        self.assert_rejected(self.run_entrypoint())
        self.assertFalse(self.config.exists())

    def test_missing_or_blank_key_is_rejected(self):
        for key in (None, "", " \t\n"):
            with self.subTest(key=key):
                self.env.pop("CODEXIFY_TUNNEL_API_KEY", None)
                if key is not None:
                    self.env["CODEXIFY_TUNNEL_API_KEY"] = key
                self.assert_rejected(self.run_entrypoint())
                self.assertFalse(self.config.exists())

    def test_invalid_tunnel_ids_are_rejected(self):
        for tunnel in ("", "tunnel_example", "tunnel_" + "A" * 32,
                       TUNNEL_ID + "\n", TUNNEL_ID + '\",\"apiKey\":\"unsafe'):
            with self.subTest(tunnel=tunnel):
                self.env["CODEXIFY_TUNNEL_ID"] = tunnel
                self.assert_rejected(self.run_entrypoint())
                self.assertFalse(self.config.exists())

    def test_key_alone_does_not_start_an_unconfigured_server(self):
        self.env.pop("CODEXIFY_TUNNEL_ID")
        self.assert_rejected(self.run_entrypoint())
        self.assertFalse(self.config.exists())

    def test_help_needs_no_configuration_and_does_not_inherit_key(self):
        self.env["CODEXIFY_TUNNEL_ID"] = "invalid"
        self.assert_started(self.run_entrypoint("--help"))
        self.assertFalse(self.config.exists())

    def test_missing_template_leaves_no_partial_configuration(self):
        self.env["CODEXIFY_CONFIG_TEMPLATE"] = str(self.home / "missing-template")
        self.assert_rejected(self.run_entrypoint())
        self.assertFalse(self.config.exists())
        self.assertEqual(list(self.config.parent.iterdir()), [])

    def test_configuration_symlink_is_rejected(self):
        self.config.parent.mkdir()
        target = self.home / "other-file"
        target.write_text("preserve me")
        self.config.symlink_to(target)
        self.assert_rejected(self.run_entrypoint())
        self.assertEqual(target.read_text(), "preserve me")

    def test_secret_characters_are_literal_not_shell_or_json_code(self):
        self.env["CODEXIFY_TUNNEL_API_KEY"] = 'sk-"quoted"-$(touch injected)-\\literal'
        self.assert_started(self.run_entrypoint())
        self.assertFalse((self.home / "injected").exists())
        secret = self.home / "codexify-secrets" / "openai-api-key"
        self.assertEqual(secret.read_text(), self.env["CODEXIFY_TUNNEL_API_KEY"] + "\n")


if __name__ == "__main__":
    unittest.main()
