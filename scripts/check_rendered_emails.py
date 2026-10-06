"""Second-pass public website checks with agent-browser in a separate pinned tab.

Only current, not-deselected operational food places needing a general email.
Does not submit forms, bypass robots exclusions/challenges, or send messages.
"""

import argparse
import html
import json
import subprocess
from datetime import datetime, timezone

import placeparse
from email_discovery import (
    contact_links,
    email_role,
    extract_emails,
    host,
    public_url,
    related_hosts,
)
from scripts.capture_maps_list import browser

READ_PAGE = """(()=>{
const clone=document.body.cloneNode(true);
clone.querySelectorAll('script,style,svg,noscript').forEach(e=>e.remove());
return {url:location.href,title:document.title,text:document.body.innerText.slice(0,200000),
html:clone.outerHTML.slice(0,1500000)};
})()"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--cdp", default="9222")
    parser.add_argument("--limit", type=int)
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
    current = placeparse.current_list_cids()
    snapshot = json.loads((placeparse.OUT_DIR / "maps_saved_list.json").read_text())
    current_files = {p.get("cache_file") for p in snapshot["places"]}
    selected = []
    for file in placeparse.get_out_files():
        data = json.loads(file.read_text())
        discovery = data.get("email_discovery", {})
        sources = placeparse.sourced_emails(discovery)
        is_food = bool(
            set(data.get("types", [])) & {"restaurant", "food", "cafe", "bakery", "bar"}
        ) or data.get("food_place")
        if (
            not is_food
            or not placeparse.consider_for_outreach(data)
            or data.get("business_status") != "OPERATIONAL"
            or not data.get("website")
        ):
            continue
        if (
            placeparse.cached_cid(data) not in current
            and file.name not in current_files
        ):
            continue
        if any(
            email_role(e) in {"general/unspecified", "reservations", "allergy/dietary"}
            for e in sources
        ):
            continue
        if host(data["website"]) in {
            "facebook.com",
            "instagram.com",
            "twitter.com",
            "x.com",
            "grubhub.com",
            "doordash.com",
            "resy.com",
            "opentable.com",
            "toasttab.com",
            "squareup.com",
        }:
            continue
        if any(p["status"] == "robots_disallowed" for p in discovery.get("pages", [])):
            continue
        if discovery.get("browser_checked_at"):
            continue
        selected.append(file)
    if args.limit:
        selected = selected[: args.limit]
    if not selected:
        print("No unchecked rendered candidates; reports regenerated.", flush=True)
        placeparse.export_email_reports()
        return
    browser(command, "tab", "new", "about:blank")
    # Capture the stable new tab ID; never close the user's other tabs/browser.
    tabs = browser(command, "tab", "list")["tabs"]
    tab_id = next(t["tabId"] for t in tabs if t["active"])
    print(f"Rendered checks selected: {len(selected)}; own tab {tab_id}", flush=True)
    try:
        for index, file in enumerate(selected):
            data = json.loads(file.read_text())
            discovery = data.get(
                "email_discovery", {"sources": {}, "pages": [], "contact_forms": []}
            )
            discovery["browser_checked_at"] = datetime.now(timezone.utc).isoformat()
            discovery["browser_outcome"] = "not_found_on_rendered_pages"
            queue = [data["website"]]
            visited: set[str] = set()
            root_url = data["website"]
            withheld = set(discovery.get("candidate_sources", {})) | set(
                discovery.get("excluded_sources", {})
            )
            for _ in range(3):
                if not queue:
                    break
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                # Don't revisit pages that the HTTP pass found excluded by robots.
                if not public_url(url):
                    discovery["pages"].append(
                        {
                            "url": url,
                            "status": "browser_unsafe_or_unresolvable",
                            "emails": [],
                        }
                    )
                    continue
                try:
                    browser(command, "open", url)
                    browser(command, "wait", "--load", "domcontentloaded")
                    # Rendered text is the milestone, not perpetual analytics/network idle.
                    browser(
                        command,
                        "wait",
                        "--fn",
                        "document.body?.innerText?.trim().length>30",
                    )
                    page = browser(command, "eval", READ_PAGE)["result"]
                except (RuntimeError, subprocess.CalledProcessError):
                    discovery["pages"].append(
                        {"url": url, "status": "browser_load_error", "emails": []}
                    )
                    continue
                if not public_url(page["url"]):
                    discovery["pages"].append(
                        {
                            "url": url,
                            "status": "browser_redirect_not_public",
                            "emails": [],
                        }
                    )
                    break
                if not related_hosts(root_url, page["url"]):
                    discovery["pages"].append(
                        {
                            "url": page["url"],
                            "status": "browser_offsite_redirect",
                            "emails": [],
                        }
                    )
                    continue
                if any(
                    phrase in (page["title"] + " " + page["text"]).lower()
                    for phrase in (
                        "verify you are human",
                        "checking your browser",
                        "access denied",
                        "just a moment",
                        "security verification",
                        "this site can’t be reached",
                        "this site can't be reached",
                    )
                ):
                    discovery["pages"].append(
                        {"url": page["url"], "status": "browser_blocked", "emails": []}
                    )
                    continue
                emails = sorted(
                    extract_emails(
                        page["html"] + "<p>" + html.escape(page["text"]) + "</p>"
                    )
                    - withheld
                )
                discovery["pages"].append(
                    {"url": page["url"], "status": "browser_ok", "emails": emails}
                )
                for email in emails:
                    urls = discovery.setdefault("sources", {}).setdefault(email, [])
                    if page["url"] not in urls:
                        urls.append(page["url"])
                for link in contact_links(page["html"], page["url"]):
                    if link not in visited and link not in queue:
                        queue.append(link)
                if any(
                    email_role(e)
                    in {"general/unspecified", "reservations", "allergy/dietary"}
                    for e in emails
                ):
                    break
            if discovery.get("sources"):
                discovery["outcome"] = "found"
                discovery["browser_outcome"] = "found"
            elif any(
                p["status"].startswith("browser_") and p["status"] != "browser_ok"
                for p in discovery["pages"]
            ):
                discovery["browser_outcome"] = "incomplete_lookup"
                discovery["outcome"] = "incomplete_lookup"
            data["email_discovery"] = discovery
            data["emails"] = sorted(
                set(data.get("emails", [])) | set(discovery.get("sources", {}))
            )
            placeparse.write_json(file, data)
            print(
                f"{index + 1}/{len(selected)}: {data['name']} — {discovery['browser_outcome']}",
                flush=True,
            )
    finally:
        browser(command, "tab", "close", tab_id)
    placeparse.export_email_reports()


if __name__ == "__main__":
    main()
