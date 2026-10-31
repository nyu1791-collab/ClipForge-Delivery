import importlib.util
from pathlib import Path
import tempfile
import unittest

from imports import import_many, read_manifest

spec = importlib.util.spec_from_file_location("workstation_manage", Path(__file__).resolve().parents[1] / "workstation/manage.py")
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class WorkstationImportTests(unittest.TestCase):
    def test_package_moved_to_another_pc_can_be_imported_without_original_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "completed"
            source.mkdir()
            (source / "video.mp4").write_bytes(b"synthetic video copy fixture")
            text = "1\n00:00:01,000 --> 00:00:03,500\n元の字幕と時刻\n"
            (source / "captions.srt").write_text(text, encoding="utf-8")
            manage.package(source, root / "old-pc", mode="tiktok", title="納品見出し")
            (root / "old-pc").rename(root / "new-pc")
            entries = read_manifest(root / "new-pc/manifest.json", "tiktok")
            self.assertEqual(entries[0]["title"], "納品見出し")
            results = import_many(entries, root / "delivery-data")
            self.assertEqual(results[0]["status"], "imported")
            imported = Path(results[0]["directory"])
            self.assertEqual((imported / "captions.srt").read_text(encoding="utf-8"), text)
            self.assertTrue((imported / "video.mp4").is_file())


if __name__ == "__main__":
    unittest.main()
