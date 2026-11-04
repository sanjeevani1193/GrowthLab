"""Acquisition safeguards tested without network access or real dataset files."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from growthlab.acquire import MONTHS, acquire


def metadata(endpoint):
    if endpoint == "view":
        return {"currentVersionNumber": 6, "licenseName": "Data files © Original Authors",
                "description": "You can use this dataset for free"}
    return {"datasetFiles": [{"name": month + ".csv", "totalBytes": 10} for month in MONTHS]}


class AcquisitionSafetyTests(unittest.TestCase):
    @patch("growthlab.acquire.get_metadata", side_effect=metadata)
    @patch("growthlab.acquire.shutil.disk_usage", return_value=SimpleNamespace(free=1))
    def test_insufficient_disk_stops_before_download(self, disk, meta):
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen") as network:
            with self.assertRaisesRegex(RuntimeError, "free bytes"):
                acquire(Path(directory))
            network.assert_not_called()

    @patch("growthlab.acquire.get_metadata", side_effect=metadata)
    @patch("growthlab.acquire.shutil.disk_usage", return_value=SimpleNamespace(free=100 * 1024**3))
    def test_unmanaged_existing_file_not_overwritten(self, disk, meta):
        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen") as network:
            root = Path(directory)
            (root / "data/raw").mkdir(parents=True)
            existing = root / "data/raw/2019-Oct.csv"
            existing.write_text("keep me")
            with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                acquire(root)
            self.assertEqual(existing.read_text(), "keep me")
            network.assert_not_called()

    def test_license_change_stops_before_download(self):
        def changed(endpoint):
            result = metadata(endpoint)
            if endpoint == "view":
                result["licenseName"] = "changed"
            return result
        with tempfile.TemporaryDirectory() as directory, patch("growthlab.acquire.get_metadata", side_effect=changed):
            with patch("urllib.request.urlopen") as network:
                with self.assertRaisesRegex(ValueError, "License changed"):
                    acquire(Path(directory))
                network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
