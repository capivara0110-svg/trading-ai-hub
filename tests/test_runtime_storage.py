import tempfile
import unittest
from pathlib import Path

from packages.strategy_core.datasets import DatasetStore


class RuntimeStorageTests(unittest.TestCase):
    def test_dataset_store_uses_explicit_persistent_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "app"
            storage = Path(temp) / "volume"
            root.mkdir()
            sample = root / "sample.csv"
            sample.write_text("time,open,high,low,close,volume\n", encoding="utf-8")

            store = DatasetStore(root, sample, uploads=storage)

            self.assertEqual(storage, store.uploads)
            self.assertEqual(storage / "state.json", store.state_path)
            self.assertTrue(storage.exists())


if __name__ == "__main__":
    unittest.main()
