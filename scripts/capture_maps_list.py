"""Capture the open Maps list from a response the authenticated UI already requested.

No Takeout, auth export, reconstructed RPCs, or modification of saved lists.
Fail closed if the observed response cannot be matched to the open list.
"""

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

CARD_SELECTOR = '[role="main"]:not([aria-label]) button.SMP2wb'


def browser(command: list[str], *args: str) -> dict[str, Any]:
    result = subprocess.run(
        command + list(args), capture_output=True, text=True, check=True
    )
    body = json.loads(result.stdout)
    if not body.get("success"):
        raise RuntimeError("agent-browser failed")
    return body["data"]


def parse_list_response(body: str, title: str, count: int) -> list[dict[str, str]]:
    """Extract only place names, public addresses, and CIDs, not account/author metadata."""
    start = body.find("[")
    if start < 0:
        raise ValueError("Not a Maps JSON response")
    root = json.loads(body[start:])[0]
    if root[4] != title or root[12] != count or len(root[8]) != count:
        raise ValueError("Response title/count differs from the open list")
    places = []
    for entry in root[8]:
        signed_cid = int(entry[1][6][1])
        if not -(1 << 63) <= signed_cid < (1 << 64):
            raise ValueError("Invalid CID")
        cid = str(signed_cid & ((1 << 64) - 1))
        places.append(
            {"list_name": entry[2], "cid": cid, "list_address": entry[1][2] or ""}
        )
    if len({p["cid"] for p in places}) != count:
        raise ValueError("Duplicate list IDs; cannot prove complete membership")
    return places


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--cdp", default="9222")
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument(
        "--output", type=Path, default=Path("output/maps_saved_list.json")
    )
    args = parser.parse_args()
    command = [
        "agent-browser",
        "--session",
        args.session,
        "--cdp",
        args.cdp,
        "--pin-tab",
        "--json",
    ]
    initial = browser(
        command,
        "eval",
        "({url:location.href,title:document.querySelector('[role=main]:not([aria-label]) h1')?.textContent,description:document.querySelector('[role=main]:not([aria-label]) h2')?.textContent})",
    )["result"]
    count_match = re.search(r"([\d,]+) places", initial.get("description") or "")
    list_match = re.search(r"!2s([^!]+)!3e2", initial["url"])
    if (
        initial["title"] != "Want to go"
        or not count_match
        or int(count_match[1].replace(",", "")) != args.expected_count
        or not list_match
    ):
        raise RuntimeError(
            "Open the intended shared Want to go list; title/count/list ID did not match"
        )
    names = browser(
        command,
        "eval",
        f"Array.from(document.querySelectorAll({json.dumps(CARD_SELECTOR)})).map(e=>e.querySelector('.fontHeadlineSmall')?.textContent)",
    )["result"]
    if not names:
        raise RuntimeError("No list cards visible; verify the open list")
    requests = browser(
        command, "network", "requests", "--filter", "entitylist/getlist"
    )["requests"]
    for request in reversed(requests):
        if urlsplit(
            request["url"]
        ).path != "/maps/preview/entitylist/getlist" or list_match[1] not in unquote(
            request["url"]
        ):
            continue
        try:
            response = browser(command, "network", "request", request["requestId"])
            if response["status"] != 200:
                continue
            places = parse_list_response(
                response["responseBody"], initial["title"], args.expected_count
            )
            if len({p["list_name"] for p in places} & set(names)) < 0.8 * len(
                set(names)
            ):
                continue
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
        ):
            continue
        document = {
            "title": initial["title"],
            "description": initial["description"],
            "list_url": initial["url"],
            "expected_count": args.expected_count,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "complete": True,
            "capture_method": "observed_maps_list_response_validated_against_UI",
            "places": places,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        temporary.replace(args.output)
        print(
            f"Saved {len(places)} complete list IDs from the observed browser response."
        )
        return
    raise RuntimeError(
        "No matching complete Maps list response available. Reopen the list in this session and retry; no incomplete snapshot was saved."
    )


if __name__ == "__main__":
    main()
