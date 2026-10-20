"""Syntax-Gate: jede Python-Datei muss kompilierbar sein. Braucht keine Abhängigkeiten."""
import py_compile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestSyntax(unittest.TestCase):
    def test_all_python_files_compile(self):
        dateien = sorted(
            p for p in ROOT.rglob("*.py")
            if ".venv" not in p.parts and "node_modules" not in p.parts
        )
        self.assertGreater(len(dateien), 0, "keine Python-Dateien gefunden")
        for pfad in dateien:
            with self.subTest(datei=str(pfad.relative_to(ROOT))):
                try:
                    py_compile.compile(str(pfad), doraise=True)
                except py_compile.PyCompileError as exc:
                    self.fail(f"Syntaxfehler in {pfad.relative_to(ROOT)}: {exc}")


if __name__ == "__main__":
    unittest.main()
