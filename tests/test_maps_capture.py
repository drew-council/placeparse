import json
import unittest

from scripts.capture_maps_list import parse_list_response


def payload(cids: list[int], title: str = "Want to go") -> str:
    root = [None] * 13
    root[4] = title
    entries = []
    for index, cid in enumerate(cids):
        identity = [None] * 8
        identity[2] = f"Restaurant {index}, public address"
        identity[6] = ["0", str(cid)]
        entry = [None, identity, f"Restaurant {index}"]
        entries.append(entry)
    root[8] = entries
    root[12] = len(entries)
    return ")]}'\n" + json.dumps([root])


class MapsCaptureTests(unittest.TestCase):
    def test_signed_ids_and_only_selected_public_data(self):
        places = parse_list_response(payload([-1, 42]), "Want to go", 2)
        self.assertEqual(places[0]["cid"], str((1 << 64) - 1))
        self.assertEqual(places[1]["cid"], "42")
        self.assertEqual(set(places[0]), {"list_name", "cid", "list_address"})

    def test_wrong_title_rejected(self):
        with self.assertRaises(ValueError):
            parse_list_response(payload([1], "Another list"), "Want to go", 1)

    def test_incomplete_count_rejected(self):
        with self.assertRaises(ValueError):
            parse_list_response(payload([1]), "Want to go", 2)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            parse_list_response(payload([1, 1]), "Want to go", 2)


if __name__ == "__main__":
    unittest.main()
