import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from click.testing import CliRunner

import email_discovery as discovery
import placeparse


class EmailDiscoveryTests(unittest.TestCase):
    def test_extracts_public_addresses_not_script_noise(self):
        html = """<script>tracking@sentry.io; asset@2x.png; hidden@vendor.com</script>
        <a href="MAILTO:INFO%40restaurant.com,chef@restaurant.com?subject=hello">Email</a>
        <p>dietary [at] restaurant [dot] com</p><p>example@example.com</p>"""
        self.assertEqual(
            discovery.extract_emails(html),
            {"info@restaurant.com", "chef@restaurant.com", "dietary@restaurant.com"},
        )

    def test_obfuscated_subdomain_not_truncated(self):
        self.assertEqual(
            discovery.extract_emails(
                "<p>dietary (at) mail (dot) restaurant (dot) com</p>"
            ),
            {"dietary@mail.restaurant.com"},
        )

    def test_cloudflare_public_email_encoding(self):
        key = 42
        encoded = bytes(
            [key] + [ord(char) ^ key for char in "info@restaurant.com"]
        ).hex()
        self.assertEqual(
            discovery.extract_emails(f'<span data-cfemail="{encoded}"></span>'),
            {"info@restaurant.com"},
        )

    def test_only_relevant_same_host_links(self):
        html = '<a href="/contact">Contact</a><a href="/about">About</a><a href="https://vendor.com/contact">Contact</a><a href="/menu.pdf">Contact menu</a><a href="/cart">Buy</a>'
        self.assertEqual(
            discovery.contact_links(html, "https://restaurant.com"),
            ["https://restaurant.com/contact", "https://restaurant.com/about"],
        )

    def test_discovers_linked_contact_page_with_source(self):
        def fake_fetch(session, url, deadline):
            if url.endswith("robots.txt"):
                return url, "User-agent: *\nAllow: /"
            if url.endswith("contact"):
                return url, '<a href="mailto:hello@restaurant.com">Email</a>'
            return url, '<a href="/contact">Contact us</a>'

        with (
            patch.object(discovery, "fetch_page", side_effect=fake_fetch),
            patch.object(discovery.time, "sleep"),
        ):
            result = discovery.discover_emails("https://restaurant.com")
        self.assertEqual(result.outcome, "found")
        self.assertEqual(
            result.sources, {"hello@restaurant.com": ["https://restaurant.com/contact"]}
        )
        self.assertEqual(len(result.pages), 2)

    def test_network_failure_not_reported_as_absence(self):
        with (
            patch.object(discovery, "fetch_page", side_effect=requests.Timeout),
            patch.object(discovery.time, "sleep"),
        ):
            result = discovery.discover_emails("https://restaurant.com")
        self.assertEqual(result.outcome, "incomplete_lookup")

    def test_vendor_and_placeholder_addresses_are_not_contacts(self):
        html = "<p>info@mysite.com billing@totalav.com placejoys.com@gmail.com support@slicelife.com support@kingdumplings.one7g.com</p>"
        self.assertEqual(discovery.extract_emails(html), set())

    def test_unrelated_redirect_requires_review(self):
        def fake_fetch(session, url, deadline):
            if url.endswith("robots.txt"):
                return url, "User-agent: *\nAllow: /"
            return "https://unrelated.com/", "<p>hello@unrelated.com</p>"

        with patch.object(discovery, "fetch_page", side_effect=fake_fetch):
            result = discovery.discover_emails("https://restaurant.com")
        self.assertEqual(result.outcome, "incomplete_lookup")
        self.assertEqual(result.sources, {})
        self.assertEqual(result.pages[0].status, "external_redirect_requires_review")

    def test_host_boundaries(self):
        self.assertTrue(
            discovery.related_hosts(
                "http://www.restaurant.com", "https://restaurant.com/contact"
            )
        )
        self.assertTrue(
            discovery.related_hosts(
                "https://restaurant.com", "https://locations.restaurant.com"
            )
        )
        self.assertFalse(
            discovery.related_hosts(
                "https://restaurant.com", "https://restaurant.com.evil.com"
            )
        )
        self.assertFalse(
            discovery.related_hosts("https://restaurant.com", "https://other.com")
        )

    def test_repeat_scan_preserves_manual_quarantine_and_legacy_email(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            file = data_dir / "restaurant.json"
            candidate = {
                "pending@restaurant.com": {
                    "urls": ["https://restaurant.com/contact"],
                    "reason": "Ownership requires review",
                }
            }
            file.write_text(
                json.dumps(
                    {
                        "name": "Restaurant",
                        "maps_cid": "1",
                        "website": "https://restaurant.com",
                        "emails": ["legacy@restaurant.com"],
                        "email_discovery": {
                            "candidate_sources": candidate,
                            "quality_review": {"note": "Pending"},
                        },
                    }
                )
            )
            result = discovery.Discovery(
                outcome="found",
                sources={"pending@restaurant.com": ["https://restaurant.com/contact"]},
            )
            with (
                patch.object(placeparse, "OUT_DIR", root),
                patch.object(placeparse, "OUT_JSON_DIR", data_dir),
                patch.object(placeparse, "discover_emails", return_value=result),
            ):
                run = CliRunner().invoke(
                    placeparse.cli, ["get-emails", "--workers", "1"]
                )
            self.assertEqual(run.exit_code, 0, run.output)
            data = json.loads(file.read_text())
            self.assertEqual(data["emails"], ["legacy@restaurant.com"])
            self.assertEqual(data["email_discovery"]["candidate_sources"], candidate)
            self.assertEqual(
                data["email_discovery"]["quality_review"]["note"], "Pending"
            )
            self.assertEqual(data["email_discovery"]["sources"], {})
            self.assertEqual(data["email_discovery"]["outcome"], "unverified_only")

    def test_no_website(self):
        self.assertEqual(discovery.discover_emails("").outcome, "no_website")

    def test_private_urls_rejected(self):
        with patch.object(
            discovery.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ):
            self.assertFalse(discovery.public_url("https://restaurant.com/contact"))
        self.assertFalse(discovery.public_url("file:///etc/passwd"))
        self.assertFalse(discovery.public_url("https://user:password@restaurant.com"))

    def test_redirect_checked_before_next_request(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        response.is_redirect = True
        response.headers = {"Location": "http://127.0.0.1/"}
        session = Mock()
        session.get.return_value = response
        with patch.object(discovery, "public_url", side_effect=[True, False]):
            with self.assertRaises(ValueError):
                discovery.fetch_page(session, "https://restaurant.com", float("inf"))
        session.get.assert_called_once()

    def test_roles(self):
        self.assertEqual(
            discovery.email_role("press@restaurant.com"), "press/marketing"
        )
        self.assertEqual(
            discovery.email_role("events@restaurant.com"), "events/catering"
        )
        self.assertEqual(
            discovery.email_role("info@restaurant.com"), "general/unspecified"
        )

    def test_reports_only_source_backed_current_open_contacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            (root / "maps_saved_list.json").write_text(
                json.dumps(
                    {
                        "complete": True,
                        "places": [
                            {
                                "cid": "1",
                                "list_name": "Open",
                                "cache_file": "open.json",
                                "scan_outcome": "browser_verified",
                            },
                            {
                                "cid": "2",
                                "list_name": "Closed",
                                "cache_file": "closed.json",
                            },
                        ],
                    }
                )
            )
            for cid, name, status in [
                ("1", "Open", "OPERATIONAL"),
                ("2", "Closed", "CLOSED_PERMANENTLY"),
                ("3", "Removed", "OPERATIONAL"),
            ]:
                data = {
                    "name": name,
                    "maps_cid": cid,
                    "food_place": True,
                    "business_status": status,
                    "emails": ["legacy@restaurant.com"],
                    "details_source": "google_maps_ui",
                    "email_discovery": {
                        "outcome": "found",
                        "sources": {
                            "info@restaurant.com": ["https://restaurant.com/contact"],
                            "press@restaurant.com": ["https://restaurant.com/about"],
                            "pending@restaurant.com": [
                                "https://restaurant.com/contact"
                            ],
                            "support@slicelife.com": ["https://restaurant.com/contact"],
                        },
                        "candidate_sources": {
                            "pending@restaurant.com": {
                                "urls": ["https://restaurant.com/contact"],
                                "reason": "Needs owner confirmation",
                            }
                        },
                        "pages": [
                            {
                                "url": "https://restaurant.com/contact",
                                "status": "browser_ok",
                            }
                        ],
                        "browser_checked_at": "now",
                    },
                }
                (data_dir / f"{name.lower()}.json").write_text(json.dumps(data))
            with (
                patch.object(placeparse, "OUT_DIR", root),
                patch.object(placeparse, "OUT_JSON_DIR", data_dir),
            ):
                placeparse.export_email_reports()
            with (root / "outreach_contacts.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r["Name"] == "Open" for r in rows))
            self.assertNotIn("legacy@restaurant.com", [r["Email"] for r in rows])
            self.assertEqual(
                next(
                    r["Suggested For Allergy Inquiry"]
                    for r in rows
                    if r["Email"].startswith("press")
                ),
                "False",
            )
            with (root / "email_coverage.csv").open() as stream:
                coverage = list(csv.DictReader(stream))
            self.assertTrue(all(not r["Failed Pages"] for r in coverage))
            with (root / "new_places.csv").open() as stream:
                new = list(csv.DictReader(stream))
            self.assertEqual(len(new), 1)
            self.assertEqual(new[0]["Details Source"], "google_maps_ui")
            self.assertNotIn("pending@restaurant.com", new[0]["Verified Emails"])
            with (root / "email_candidates_review.csv").open() as stream:
                candidates = list(csv.DictReader(stream))
            self.assertEqual(len(candidates), 3)
            self.assertTrue(all(r["Review Required"] == "True" for r in candidates))

    def test_import_uses_ids_and_avoids_name_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            old = {
                "name": "Same Name",
                "place_id": "old",
                "url": "https://maps.google.com/?cid=1",
                "emails": ["old@restaurant.com"],
            }
            old_file = data_dir / "same_name.json"
            old_file.write_text(json.dumps(old))
            snapshot = root / "list.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "complete": True,
                        "expected_count": 2,
                        "places": [
                            {"cid": "1", "list_name": "Renamed"},
                            {"cid": "2", "list_name": "Same Name"},
                        ],
                    }
                )
            )
            response = Mock()
            response.json.return_value = {
                "status": "OK",
                "result": {
                    "name": "Same Name",
                    "place_id": "new",
                    "url": "https://maps.google.com/?cid=2",
                },
            }
            with (
                patch.object(placeparse, "OUT_JSON_DIR", data_dir),
                patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "secret"}),
                patch.object(placeparse.requests, "get", return_value=response),
                patch.object(placeparse.time, "sleep"),
            ):
                result = CliRunner().invoke(
                    placeparse.cli, ["scan-new-places", str(snapshot)]
                )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(old_file.read_text()), old)
            self.assertTrue((data_dir / "same_name__2.json").exists())
            self.assertEqual(response.json.call_count, 1)


if __name__ == "__main__":
    unittest.main()
