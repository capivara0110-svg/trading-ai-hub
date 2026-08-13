import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from packages.strategy_core.execution import claim_order


class ExecutionDemoGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "execution.json"
        self.state_path.write_text(
            json.dumps({"order": {"id": "order-1", "status": "PENDING"}}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_demo_only_rejects_real_account(self):
        with patch.dict(os.environ, {"AUTO_TRADE_MODE": "DEMO_ONLY"}):
            result = claim_order(self.state_path, "order-1", "REAL")
        self.assertFalse(result["claimed"])
        self.assertIn("conta demo", result["reason"])

    def test_demo_only_rejects_missing_account_confirmation(self):
        with patch.dict(os.environ, {"AUTO_TRADE_MODE": "DEMO_ONLY"}):
            result = claim_order(self.state_path, "order-1")
        self.assertFalse(result["claimed"])

    def test_demo_only_accepts_demo_account(self):
        with patch.dict(os.environ, {"AUTO_TRADE_MODE": "DEMO_ONLY"}):
            result = claim_order(self.state_path, "order-1", "DEMO")
        self.assertTrue(result["claimed"])
        self.assertEqual("CLAIMED", result["order"]["status"])

    def test_demo_only_accepts_contest_account(self):
        with patch.dict(os.environ, {"AUTO_TRADE_MODE": "DEMO_ONLY"}):
            result = claim_order(self.state_path, "order-1", "CONTEST")
        self.assertTrue(result["claimed"])

    def test_status_resets_stale_daily_count_without_deleting_audit(self):
        self.state_path.write_text(
            json.dumps({"orderDay": "2020-01-01", "ordersToday": 2, "orders": {}}),
            encoding="utf-8",
        )
        from packages.strategy_core.execution import execution_status

        result = execution_status(self.state_path)
        self.assertEqual(0, result["ordersToday"])
        self.assertEqual("2020-01-01", result["orderDay"])


if __name__ == "__main__":
    unittest.main()
