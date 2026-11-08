import os
import tempfile
import unittest
from pathlib import Path

from acp_funcforge.filesystem import (
    detect_language,
    format_code_context,
    read_text_file,
    scan_code_files,
    write_text_file,
)


class FilesystemTests(unittest.TestCase):
    def test_write_and_read_any_language(self):
        with tempfile.TemporaryDirectory() as td:
            cases = [
                ("hello.py", "print('hi')\n", "python"),
                ("main.go", "package main\n", "go"),
                ("lib.rs", "pub fn f() {}\n", "rust"),
                ("app.ts", "export const x=1;\n", "typescript"),
                ("Program.cs", "class P {}\n", "csharp"),
                ("index.html", "<!doctype html>", "html"),
                ("schema.sql", "select 1;", "sql"),
                ("unknown.zzz", "content", "zzz"),
            ]
            for name, content, lang in cases:
                path = write_text_file(name, content, base_dir=td)
                cf = read_text_file(name, base_dir=td)
                self.assertEqual(cf.path, path)
                self.assertEqual(cf.content, content)
                self.assertEqual(cf.language_hint, lang)

    def test_detect_language(self):
        self.assertEqual(detect_language("Dockerfile"), "dockerfile")
        self.assertEqual(detect_language("Makefile"), "makefile")
        self.assertEqual(detect_language("x.rb"), "ruby")

    def test_scan_and_context(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "a.py").write_text("a=1", encoding="utf-8")
            Path(td, "b.js").write_text("let b=1", encoding="utf-8")
            Path(td, "sub").mkdir()
            Path(td, "sub/c.rs").write_text("fn c(){}", encoding="utf-8")
            files = scan_code_files(td, include_globs=["*.py", "*.rs"])
            rels = sorted(f.relpath for f in files)
            self.assertEqual(rels, ["a.py", os.path.join("sub", "c.rs")])
            ctx = format_code_context(files, max_chars=10_000)
            self.assertIn("--- FILE: a.py", ctx)
            self.assertIn("a=1", ctx)

    def test_relative_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as td:
            p = write_text_file(os.path.join(td, "abs.txt"), "x", base_dir="/")
            self.assertTrue(os.path.isabs(p))
            cf = read_text_file("abs.txt", base_dir=td)
            self.assertEqual(cf.content, "x")


if __name__ == "__main__":
    unittest.main()
