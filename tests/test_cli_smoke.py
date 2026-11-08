import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CLISmokeTests(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        return subprocess.run([sys.executable, "-m", "acp_funcforge.cli", *args], cwd=cwd or str(ROOT), env=env, capture_output=True, text=True, timeout=30)

    def test_help(self):
        p = self.run_cli("--help")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("read-code", p.stdout)
        self.assertIn("decompose", p.stdout)

    def test_write_read_roundtrip(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            w = self.run_cli("write-code", os.path.join(td, "x.go"), "--content", "package main\n")
            self.assertEqual(w.returncode, 0, w.stderr + w.stdout)
            r = self.run_cli("read-code", os.path.join(td, "x.go"))
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            data = json.loads(r.stdout)
            self.assertEqual(data["language"], "go")
            self.assertIn("package main", data["content"])


if __name__ == "__main__":
    unittest.main()
