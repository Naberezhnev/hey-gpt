import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from hey_gpt.model_setup import MODEL_NAME, REQUIRED, extract_model
from hey_gpt.settings import load_selectors, save_selectors


class SettingsTests(unittest.TestCase):
    def test_corrupt_and_wrong_shaped_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "selectors.json"
            for value in ("not JSON", "[]", "null", '{"send": 42}', '{"unknown": {}}',
                          '{"composer":{"control_type":"EditControl","name":null,"automation_id":"x"}}'):
                path.write_text(value, encoding="utf-8")
                selectors, warning = load_selectors(path)
                self.assertEqual(selectors, {})
                self.assertTrue(warning)

    def test_calibration_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings" / "selectors.json"
            selectors = {"send": {"control_type": "ButtonControl", "name": "Отправить", "automation_id": "send"}}
            save_selectors(path, selectors)
            self.assertEqual(load_selectors(path), (selectors, ""))
            self.assertFalse(path.with_suffix(".tmp").exists())


class ModelArchiveTests(unittest.TestCase):
    def archive(self, folder, extra=None):
        path = Path(folder) / "model.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for required in REQUIRED:
                archive.writestr(MODEL_NAME + "/" + required, "test")
            if extra:
                archive.writestr(extra, "invalid")
        return path

    def test_model_extracts_inside_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "unpacked"
            result = extract_model(self.archive(folder), target)
            self.assertEqual(result, (target / MODEL_NAME).resolve())
            self.assertTrue((result / REQUIRED[0]).exists())

    def test_traversal_is_rejected_before_any_extraction(self):
        for entry in (MODEL_NAME + "/../../escaped.txt", "/absolute.txt", "other/file.txt",
                      MODEL_NAME + "/..\\escaped.txt"):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "unpacked"
                with self.assertRaises(ValueError):
                    extract_model(self.archive(folder, entry), target)
                self.assertFalse(target.exists())

    def test_incomplete_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(MODEL_NAME + "/readme", "test")
            with self.assertRaises(ValueError):
                extract_model(path, Path(folder) / "unpacked")
