import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app


class ExperimentRoutesTest(unittest.TestCase):
    def test_records_decision_to_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "decisions.jsonl"
            os.environ["EXPERIMENT_DECISION_LOG"] = str(log_path)
            try:
                response = TestClient(app).post(
                    "/api/v1/experiment/decision",
                    json={
                        "participant_id": "P01",
                        "trial": 1,
                        "news_id": 3,
                        "condition": "plugin_assistant",
                        "decision": "reject",
                        "timestamp": "2026-06-05T00:00:00.000Z",
                    },
                )
            finally:
                os.environ.pop("EXPERIMENT_DECISION_LOG", None)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})

            rows = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(rows), 1)
            record = json.loads(rows[0])
            self.assertEqual(record["participant_id"], "P01")
            self.assertEqual(record["condition"], "plugin_assistant")
            self.assertEqual(record["decision"], "reject")
            self.assertIn("received_at", record)


if __name__ == "__main__":
    unittest.main()
