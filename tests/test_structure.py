"""Struktur- und Hygiene-Gate: Pflichtdateien vorhanden, .gitignore deckt Geheimnisse ab."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PFLICHT = [
    "README.md",
    "requirements.txt",
    ".gitignore",
    "backend/api/main.py",
    "backend/api/main_v2.py",
    "backend/models/database.py",
    "frontend/kiosk/index.html",
    "frontend/dashboard/index.html",
    "frontend/frs-archive/index.html",
]
MUSS_IGNORIEREN = [".env", "*.key", "secrets.yaml"]


class TestStruktur(unittest.TestCase):
    def test_pflichtdateien(self):
        for rel in PFLICHT:
            with self.subTest(datei=rel):
                self.assertTrue((ROOT / rel).is_file(), f"Pflichtdatei fehlt: {rel}")

    def test_gitignore_deckt_geheimnisse(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        zeilen = {z.strip() for z in text.splitlines()}
        for muster in MUSS_IGNORIEREN:
            with self.subTest(muster=muster):
                self.assertIn(muster, zeilen, f".gitignore deckt {muster!r} nicht ab")

    def test_requirements_nennt_kernabhaengigkeiten(self):
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        for paket in ("fastapi", "uvicorn", "aiosqlite"):
            with self.subTest(paket=paket):
                self.assertIn(paket, text, f"{paket} fehlt in requirements.txt")


if __name__ == "__main__":
    unittest.main()
