import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import placeparse
from scripts.export_text_contacts import export


class TextContactTests(unittest.TestCase):
    def test_scope_and_unverified_or_limited_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "data"
            cache.mkdir()
            records = [
                ("Cafe", "OPERATIONAL", ["cafe"], "general inquiry", True),
                (
                    "Closed",
                    "CLOSED_PERMANENTLY",
                    ["restaurant"],
                    "general inquiry",
                    True,
                ),
                ("Bar only", "OPERATIONAL", ["bar"], "general inquiry", True),
                ("Verified pub", "OPERATIONAL", ["bar"], "general inquiry", True),
                ("Bakery", "CLOSED_TEMPORARILY", ["bakery"], "general inquiry", True),
                ("Review form", "OPERATIONAL", ["food"], "general inquiry", False),
                ("Booking", "OPERATIONAL", ["restaurant"], "reservation request", True),
            ]
            members = []
            for i, (name, status, types, purpose, confirmed) in enumerate(records):
                filename = f"{i}.json"
                members.append(
                    {"cid": str(i), "list_name": name, "cache_file": filename}
                )
                (cache / filename).write_text(
                    json.dumps(
                        {
                            "name": name,
                            "business_status": status,
                            "types": types,
                            "email_discovery": {
                                "sources": {
                                    "pending@restaurant.com": ["https://directory.com"]
                                },
                                "candidate_sources": {
                                    "pending@restaurant.com": {
                                        "urls": ["https://directory.com"],
                                        "reason": "Unconfirmed",
                                    }
                                },
                            },
                            "text_contact_discovery": {
                                "food_service_evidence": (
                                    {
                                        "url": "https://restaurant.com/menu",
                                        "quote": "Kitchen menu",
                                    }
                                    if name == "Verified pub"
                                    else None
                                ),
                                "channels": [
                                    {
                                        "kind": "contact_form",
                                        "purpose": purpose,
                                        "url": "https://restaurant.com/contact",
                                        "business_match_confirmed": confirmed,
                                    }
                                ],
                                "social_profiles": [
                                    {
                                        "url": "https://instagram.com/restaurant",
                                        "messaging_verified": False,
                                    }
                                ],
                            },
                        }
                    )
                )
            (root / "maps_saved_list.json").write_text(
                json.dumps(
                    {
                        "complete": True,
                        "places": members,
                    }
                )
            )
            with (
                patch.object(placeparse, "OUT_DIR", root),
                patch.object(placeparse, "OUT_JSON_DIR", cache),
            ):
                counts = export()
            self.assertEqual(counts["eligible"], 5)
            self.assertEqual(counts["email_or_general_form_places"], 3)
            with (root / "food_text_contacts.csv").open() as stream:
                rows = {r["Name"]: r for r in csv.DictReader(stream)}
            self.assertEqual(
                set(rows), {"Cafe", "Bakery", "Review form", "Booking", "Verified pub"}
            )
            self.assertTrue(all(not r["General Inquiry Emails"] for r in rows.values()))
            self.assertFalse(rows["Review form"]["General Contact Forms"])
            self.assertFalse(rows["Booking"]["General Contact Forms"])
            self.assertIn(
                "reservation request", rows["Booking"]["Limited Purpose Forms"]
            )

    def test_hr_is_not_general_inquiry(self):
        from email_discovery import email_role

        self.assertEqual(email_role("hr@restaurant.com"), "careers")
        self.assertEqual(email_role("chris@restaurant.com"), "general/unspecified")
        self.assertEqual(email_role("hr@www.chubbygroup.com"), "careers")


if __name__ == "__main__":
    unittest.main()
