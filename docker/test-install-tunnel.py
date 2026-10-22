"""Check archive pinning and packaging with local fixtures, never the network."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent


class TunnelInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codexify tunnel ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "release.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("tunnel-client-runtime", "test binary")
            archive.writestr("THIRD_PARTY_LICENSES.txt", "third-party notice")
            for name in ("LICENSE", "NOTICE", "tunnel-client-runtime-linux-amd64-licenses.txt",
                         "tunnel-client-runtime-linux-arm64-licenses.txt"):
                archive.writestr(name, "test notice")
        self.checksum = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.source = self.root / "openai_tunnel.rs"
        self.source.write_text(
            'pub const TUNNEL_CLIENT_VERSION: &str = "0.0.12";\n'
            + ''.join(f'        ("linux", "{arch}") => "{self.checksum}",\n'
                      for arch in ("amd64", "arm64")))
        self.output = self.root / "output"
        self.output.mkdir()
        self.binary = self.output / "tunnel-client-runtime"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        curl = self.bin / "curl"
        curl.write_text('''#!/bin/sh
while [ "$#" -gt 0 ]; do
    if [ "$1" = "--output" ]; then cp "$TEST_ARCHIVE" "$2"; exit 0; fi
    shift
done
exit 1
''')
        curl.chmod(0o755)
        self.env = dict(os.environ, TEST_ARCHIVE=str(self.archive),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])

    def install(self, arch="amd64"):
        return subprocess.run(["sh", str(ROOT / "install-tunnel.sh"), arch,
                               str(self.source), str(self.binary)], env=self.env,
                              text=True, capture_output=True)

    def test_both_architectures_preserve_binary_and_notices(self):
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                result = self.install(arch)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.binary.read_text(), "test binary")
                self.assertTrue(os.access(self.binary, os.X_OK))
                self.assertFalse((self.output / "tunnel-licenses" / "tunnel-client-runtime").exists())
                self.assertEqual((self.output / "tunnel-licenses" / "THIRD_PARTY_LICENSES.txt").read_text(),
                                 "third-party notice")
                for name in ("LICENSE", "NOTICE", f"tunnel-client-runtime-linux-{arch}-licenses.txt"):
                    self.assertEqual((self.output / "tunnel-licenses" / name).read_text(), "test notice")

    def test_archive_does_not_need_an_architecture_named_license_report(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("tunnel-client-runtime", "test binary")
            for name in ("LICENSE", "NOTICE", "THIRD_PARTY_LICENSES.txt"):
                archive.writestr(name, "test notice")
        checksum = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.source.write_text(self.source.read_text().replace(self.checksum, checksum))
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output / "tunnel-licenses" / "THIRD_PARTY_LICENSES.txt").read_text(),
                         "test notice")

    def test_missing_primary_license_fails_before_installing(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("tunnel-client-runtime", "test binary")
            archive.writestr("NOTICE", "test notice")
        checksum = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.source.write_text(self.source.read_text().replace(self.checksum, checksum))
        self.assertNotEqual(self.install().returncode, 0)
        self.assertFalse(self.binary.exists())

    def test_checksum_mismatch_fails_before_installing(self):
        self.source.write_text(self.source.read_text().replace(self.checksum, "0" * 64))
        self.assertNotEqual(self.install().returncode, 0)
        self.assertFalse(self.binary.exists())

    def test_missing_source_pins_fail_closed(self):
        self.source.write_text("// Source format changed\n")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertFalse(self.binary.exists())

    def test_unsupported_architecture_fails(self):
        self.assertNotEqual(self.install("riscv64").returncode, 0)
        self.assertFalse(self.binary.exists())


if __name__ == "__main__":
    unittest.main()
