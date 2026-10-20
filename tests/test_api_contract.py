"""API-Contract-Gate: Routen werden per AST gelesen (kein Import, keine Abhängigkeiten).

Prüft drei Dinge, die im Betrieb still kaputtgehen:
1. Es gibt überhaupt Routen.
2. Kein (Methode, Pfad)-Paar ist doppelt definiert - sonst überschreibt FastAPI
   die erste Definition und der Endpunkt ist faktisch verschwunden.
3. Kein Funktionsname wird für zwei verschiedene Routen verwendet.
"""
import ast
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DATEIEN = [ROOT / "backend" / "api" / "main.py", ROOT / "backend" / "api" / "main_v2.py"]
HTTP_METHODEN = {"get", "post", "put", "patch", "delete", "head", "options"}


def routen(pfad: Path):
    baum = ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
    for knoten in ast.walk(baum):
        if not isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dek in knoten.decorator_list:
            if not isinstance(dek, ast.Call):
                continue
            ziel = dek.func
            if not (isinstance(ziel, ast.Attribute) and ziel.attr in HTTP_METHODEN):
                continue
            if not dek.args or not isinstance(dek.args[0], ast.Constant):
                continue
            yield ziel.attr.upper(), dek.args[0].value, knoten.name


class TestApiContract(unittest.TestCase):
    def test_api_dateien_vorhanden(self):
        for pfad in API_DATEIEN:
            with self.subTest(datei=pfad.name):
                self.assertTrue(pfad.is_file(), f"{pfad.name} fehlt")

    def test_routen_vorhanden(self):
        alle = []
        for pfad in API_DATEIEN:
            if pfad.is_file():
                alle.extend(routen(pfad))
        self.assertGreaterEqual(len(alle), 10, "zu wenige Routen - API unvollständig?")

    def test_keine_doppelten_routen(self):
        for pfad in API_DATEIEN:
            if not pfad.is_file():
                continue
            paare = Counter((m, p) for m, p, _ in routen(pfad))
            doppelt = {k: v for k, v in paare.items() if v > 1}
            with self.subTest(datei=pfad.name):
                self.assertEqual(doppelt, {}, f"doppelte Routen in {pfad.name}: {doppelt}")

    def test_routen_namen_eindeutig(self):
        for pfad in API_DATEIEN:
            if not pfad.is_file():
                continue
            namen = Counter(n for _, _, n in routen(pfad))
            doppelt = {k: v for k, v in namen.items() if v > 1}
            with self.subTest(datei=pfad.name):
                self.assertEqual(doppelt, {}, f"mehrfach genutzte Funktionsnamen in {pfad.name}: {doppelt}")


if __name__ == "__main__":
    unittest.main()
