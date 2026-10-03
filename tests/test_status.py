import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from click.testing import CliRunner

import placeparse


class StatusTests(unittest.TestCase):
    def test_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            result = CliRunner().invoke(placeparse.cli, ["refresh-status"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("GOOGLE_MAPS_API_KEY", result.output)

    def test_denied_stops(self):
        response = Mock()
        response.json.return_value = {"status": "REQUEST_DENIED"}
        with patch.object(placeparse.requests, "get", return_value=response):
            with self.assertRaisesRegex(Exception, "REQUEST_DENIED"):
                placeparse.fetch_business_status("id", "secret")

    def test_error_does_not_leak_key(self):
        with patch.object(
            placeparse.requests, "get", side_effect=requests.Timeout("key=secret")
        ):
            status, note = placeparse.fetch_business_status("id", "secret")
        self.assertEqual(status, "FETCH_ERROR")
        self.assertNotIn("secret", note)

    def test_unknown_not_assumed_closed(self):
        response = Mock()
        response.json.return_value = {"status": "NOT_FOUND"}
        with patch.object(placeparse.requests, "get", return_value=response):
            self.assertEqual(
                placeparse.fetch_business_status("id", "secret"), ("NOT_FOUND", "")
            )
        response.json.return_value = {"status": "OK", "result": {}}
        with patch.object(placeparse.requests, "get", return_value=response):
            self.assertEqual(
                placeparse.fetch_business_status("id", "secret")[0], "UNKNOWN"
            )

    def test_refresh_preserves_contacts_and_failed_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            original = {
                "name": "Example",
                "place_id": "id",
                "emails": ["a@b.com"],
                "website": "https://example.org",
                "business_status": "OPERATIONAL",
            }
            file = data_dir / "example.json"
            file.write_text(json.dumps(original))
            with (
                patch.object(placeparse, "OUT_JSON_DIR", data_dir),
                patch.object(placeparse, "OUT_DIR", root),
                patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "secret"}),
                patch.object(
                    placeparse,
                    "fetch_business_status",
                    return_value=("OK", "CLOSED_PERMANENTLY"),
                ),
            ):
                result = CliRunner().invoke(
                    placeparse.cli, ["refresh-status", "--delay", "0"]
                )
            self.assertEqual(result.exit_code, 0, result.output)
            updated = json.loads(file.read_text())
            self.assertEqual(updated["emails"], original["emails"])
            self.assertEqual(updated["website"], original["website"])
            self.assertEqual(updated["business_status"], "CLOSED_PERMANENTLY")
            self.assertIn("business_status_checked_at", updated)
            before = file.read_text()
            with (
                patch.object(placeparse, "OUT_JSON_DIR", data_dir),
                patch.object(placeparse, "OUT_DIR", root),
                patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "secret"}),
                patch.object(
                    placeparse, "fetch_business_status", return_value=("NOT_FOUND", "")
                ),
            ):
                result = CliRunner().invoke(
                    placeparse.cli, ["refresh-status", "--delay", "0"]
                )
            self.assertNotEqual(result.exit_code, 0)
            self.assertEqual(file.read_text(), before)
            self.assertIn("NOT_FOUND", (root / "place_status.csv").read_text())


if __name__ == "__main__":
    unittest.main()
