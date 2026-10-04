import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from email_discovery import discover_emails, email_role, extract_emails, valid_email
import click
import requests
import rich
import time
import re
from bs4 import BeautifulSoup
from tqdm import tqdm

PROJECT_DIR = Path(__file__).parent
SAVED_PLACES_FILE = PROJECT_DIR / "Takeout" / "Saved" / "Want to go.csv"
OUT_DIR = PROJECT_DIR / "output"
OUT_JSON_DIR = OUT_DIR / "restaraunt_data"

ALPHANUM_RE = re.compile(r"[^a-zA-Z0-9_-]")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.IGNORECASE)


def get_api_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise click.ClickException(
            "Set GOOGLE_MAPS_API_KEY (see README.md for 1Password setup)."
        )
    return key


def query_save_place(row: dict[str, str]):
    original_title = row.get("Title", "")
    title = ALPHANUM_RE.sub("", original_title.lower().replace(" ", "_"))
    click.secho(title, fg="blue", bold=True)

    url = row.get("URL")
    if not url:
        click.secho("No URL found", fg="red", err=True)
        return
    click.secho(url, fg="yellow")

    hex_cid = url.split(":")[-1]
    cid = int(hex_cid, 16)
    click.echo(cid)

    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={"cid": cid, "key": get_api_key()},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()["result"]
    except Exception as e:
        click.secho(
            f"Error for id: {cid}, title:{title}\n{type(e).__name__}",
            fg="red",
            err=True,
        )
        return
    rich.print(result)

    row["result"] = result

    out_file = OUT_JSON_DIR / f"{title}.json"
    OUT_JSON_DIR.mkdir(parents=True, exist_ok=True)
    with out_file.open("w") as f:
        json.dump(result, f, indent=2)


@click.group()
def cli():
    """Script for various parsing on saved google maps lists"""


@cli.command()
def query_list() -> None:
    """Query the list of saved places' google maps data and save as json"""
    get_api_key()
    with SAVED_PLACES_FILE.open() as f:
        rows = list(csv.DictReader(f))
        for i, row in tqdm(enumerate(rows), total=len(rows)):
            click.secho(f"\nQuerying row {i}...", fg="blue", italic=True)
            query_save_place(row)
            time.sleep(1)


def extract_emails_from_html(html: str) -> set[str]:
    return extract_emails(html)


def write_json(file: Path, data: dict) -> None:
    temporary = file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(file)


def cached_cid(data: dict) -> str:
    if data.get("maps_cid"):
        return str(data["maps_cid"])
    return parse_qs(urlsplit(data.get("url", "")).query).get("cid", [""])[0]


def current_list_cids() -> set[str]:
    file = OUT_DIR / "maps_saved_list.json"
    if not file.exists():
        return set()
    snapshot = json.loads(file.read_text())
    if not snapshot.get("complete"):
        raise click.ClickException(
            "Maps list snapshot is incomplete; finish capture first."
        )
    return {place["cid"] for place in snapshot["places"]}


@cli.command()
@click.argument("snapshot", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--limit", type=click.IntRange(min=1), help="Smoke-test new-place requests."
)
def scan_new_places(snapshot: Path, limit: int | None) -> None:
    """Import new Maps IDs from a complete browser capture; never remove old cache."""
    document = json.loads(snapshot.read_text())
    if not document.get("complete") or len(document.get("places", [])) != document.get(
        "expected_count"
    ):
        raise click.ClickException("Refusing incomplete Maps list capture.")
    key = get_api_key()
    OUT_JSON_DIR.mkdir(parents=True, exist_ok=True)
    known_cids: dict[str, Path] = {}
    known_ids: dict[str, Path] = {}
    for file in get_out_files():
        data = json.loads(file.read_text())
        known_cids[cached_cid(data)] = file
        known_ids[data.get("place_id", "")] = file
    added = 0
    failed = 0
    for place in tqdm(document["places"]):
        cid = place["cid"]
        if cid in known_cids:
            if place.get("scan_outcome") not in {"added", "browser_verified"}:
                place["scan_outcome"] = "existing"
            place["cache_file"] = known_cids[cid].name
            continue
        if limit and added >= limit:
            place["scan_outcome"] = "not_scanned"
            continue
        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/place/details/json",
                params={
                    "cid": cid,
                    "key": key,
                    "fields": "place_id,name,business_status,formatted_address,adr_address,formatted_phone_number,international_phone_number,website,url,types,geometry",
                },
                timeout=30,
            )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            place["scan_outcome"] = type(exc).__name__
            failed += 1
            continue
        status = body.get("status", "INVALID_RESPONSE")
        if status in {"REQUEST_DENIED", "OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"}:
            write_json(snapshot, document)
            raise click.ClickException(f"Google Places returned {status}; stopping.")
        result = body.get("result", {})
        if status != "OK" or not result.get("place_id"):
            place["scan_outcome"] = status
            failed += 1
            continue
        place_id = result["place_id"]
        if place_id in known_ids:
            place["scan_outcome"] = "existing_id_redirect"
            place["cache_file"] = known_ids[place_id].name
            known_cids[cid] = known_ids[place_id]
            continue
        slug = (
            ALPHANUM_RE.sub("", result.get("name", "place").lower().replace(" ", "_"))
            or "place"
        )
        file = OUT_JSON_DIR / f"{slug}.json"
        if file.exists():
            file = OUT_JSON_DIR / f"{slug}__{cid}.json"
        result["details_checked_at"] = datetime.now(timezone.utc).isoformat()
        if result.get("business_status"):
            result["business_status_checked_at"] = result["details_checked_at"]
        write_json(file, result)
        known_ids[place_id] = file
        known_cids[cid] = file
        place["scan_outcome"] = "added"
        place["cache_file"] = file.name
        place["place_id"] = place_id
        added += 1
        write_json(snapshot, document)
        time.sleep(0.2)
    write_json(snapshot, document)
    click.echo(
        f"Added {added} new places; {failed} failed lookups. Old records preserved."
    )
    if failed:
        raise click.ClickException(
            "Some new places were not scanned; see snapshot scan_outcome."
        )


def get_out_files() -> list[Path]:
    return sorted(OUT_JSON_DIR.glob("*.json"))


def fetch_business_status(place_id: str, key: str) -> tuple[str, str]:
    """Request only status fields; never include credentials in error output."""
    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields": "place_id,business_status",
                "key": key,
            },
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        return "FETCH_ERROR", type(exc).__name__
    status = body.get("status", "INVALID_RESPONSE")
    if status in {"REQUEST_DENIED", "OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"}:
        raise click.ClickException(
            f"Google Places returned {status}; stopping refresh."
        )
    if status != "OK":
        return status, ""
    business_status = body.get("result", {}).get("business_status", "")
    if business_status not in {
        "OPERATIONAL",
        "CLOSED_TEMPORARILY",
        "CLOSED_PERMANENTLY",
    }:
        return "UNKNOWN", "No recognized business status returned"
    return "OK", business_status


@cli.command()
@click.option(
    "--limit", type=click.IntRange(min=1), help="Limit requests for a smoke test."
)
@click.option("--delay", default=0.2, type=click.FloatRange(min=0), show_default=True)
def refresh_status(limit: int | None, delay: float) -> None:
    """Refresh existing cached places, preserving contacts; write a separate status CSV.

    Does not synchronize saved-list membership. Google API billing may apply.
    """
    key = get_api_key()
    files = get_out_files()
    if not files:
        raise click.ClickException(f"No cached places in {OUT_JSON_DIR}")
    if limit:
        files = files[:limit]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = OUT_DIR / ("place_status_sample.csv" if limit else "place_status.csv")
    counts: dict[str, int] = {}
    with report.open("w", newline="") as out:
        writer = csv.DictWriter(
            out,
            lineterminator="\n",
            fieldnames=[
                "Name",
                "Place ID",
                "Previous Status",
                "Current Status",
                "Checked At",
                "Fetch Status",
                "Note",
            ],
        )
        writer.writeheader()
        for file in tqdm(files):
            data = json.loads(file.read_text())
            place_id = data.get("place_id", "")
            previous = data.get("business_status", "")
            checked_at = datetime.now(timezone.utc).isoformat()
            status, value = (
                fetch_business_status(place_id, key)
                if place_id
                else (
                    "MISSING_PLACE_ID",
                    "No cached place ID",
                )
            )
            current = value if status == "OK" else ""
            if status == "OK":
                data["business_status"] = current
                data["business_status_checked_at"] = checked_at
                temporary = file.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(data, indent=2) + "\n")
                temporary.replace(file)
            writer.writerow(
                {
                    "Name": data.get("name", file.stem),
                    "Place ID": place_id,
                    "Previous Status": previous,
                    "Current Status": current,
                    "Checked At": checked_at,
                    "Fetch Status": status,
                    "Note": "" if status == "OK" else value,
                }
            )
            out.flush()
            label = current or status
            counts[label] = counts.get(label, 0) + 1
            time.sleep(delay)
    click.echo(f"Status report: {report}")
    click.echo(json.dumps(counts, indent=2))
    if any(
        label not in {"OPERATIONAL", "CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"}
        for label in counts
    ):
        raise click.ClickException(
            "Some places could not be verified; see the status report."
        )


@cli.command()
@click.option("--limit", type=click.IntRange(min=1))
@click.option(
    "--workers", default=4, type=click.IntRange(min=1, max=8), show_default=True
)
@click.option(
    "--max-pages", default=6, type=click.IntRange(min=1, max=12), show_default=True
)
@click.option(
    "--only-unchecked",
    is_flag=True,
    help="Resume without repeating completed website scans.",
)
def get_emails(
    limit: int | None, workers: int, max_pages: int, only_unchecked: bool
) -> None:
    """Check public websites and linked contact pages, including already cached emails."""
    files = get_out_files()
    if limit:
        files = files[:limit]
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        jobs = {}
        for file in files:
            data = json.loads(file.read_text())
            if only_unchecked and data.get("email_discovery"):
                continue
            jobs[
                executor.submit(discover_emails, data.get("website", ""), max_pages)
            ] = (file, data)
        for future in tqdm(as_completed(jobs), total=len(jobs)):
            file, data = jobs[future]
            discovery = future.result()
            previous = data.get("email_discovery", {})
            withheld = set(previous.get("candidate_sources", {})) | set(
                previous.get("excluded_sources", {})
            )
            discovery.sources = {
                email: urls
                for email, urls in discovery.sources.items()
                if email not in withheld
            }
            if discovery.outcome == "found" and not discovery.sources:
                discovery.outcome = (
                    "unverified_only"
                    if previous.get("candidate_sources")
                    else "incomplete_lookup"
                )
            old_emails = set(data.get("emails", []))
            if data.get("email"):
                old_emails.add(data["email"])
            data["emails"] = sorted(old_emails | set(discovery.sources))
            data["email_discovery"] = discovery.to_dict()
            for field in (
                "candidate_sources",
                "excluded_sources",
                "quality_review",
                "quality_reviewed_at",
            ):
                if field in previous:
                    data["email_discovery"][field] = previous[field]
            write_json(file, data)
            counts[discovery.outcome] = counts.get(discovery.outcome, 0) + 1
    snapshot = OUT_DIR / "maps_saved_list.json"
    if snapshot.exists() and not json.loads(snapshot.read_text()).get("complete"):
        click.echo(
            "Website scans saved; finish Maps capture before exporting outreach reports."
        )
    else:
        export_email_reports()
    click.echo(json.dumps(counts, indent=2))


def bad_email(email: str) -> bool:
    return not valid_email(email) or email_role(email) == "platform/vendor"


def sourced_emails(discovery: dict) -> dict[str, list[str]]:
    """Keep quarantined/invalid mailboxes out of every recipient-facing report."""
    withheld = set(discovery.get("candidate_sources", {})) | set(
        discovery.get("excluded_sources", {})
    )
    return {
        email: urls
        for email, urls in discovery.get("sources", {}).items()
        if urls and not bad_email(email) and email not in withheld
    }


def export_email_reports() -> None:
    """Coverage for all cached places; sourced addresses for current, open food places."""
    current = current_list_cids()
    snapshot_file = OUT_DIR / "maps_saved_list.json"
    listed_files = (
        {p.get("cache_file") for p in json.loads(snapshot_file.read_text())["places"]}
        if snapshot_file.exists()
        else set()
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    food_types = {
        "restaurant",
        "food",
        "cafe",
        "bakery",
        "bar",
        "meal_takeaway",
        "meal_delivery",
    }
    with (
        (OUT_DIR / "email_coverage.csv").open("w", newline="") as coverage,
        (OUT_DIR / "outreach_contacts.csv").open("w", newline="") as outreach,
    ):
        summary = csv.DictWriter(
            coverage,
            lineterminator="\n",
            fieldnames=[
                "Name",
                "Place ID",
                "On Saved List",
                "Food Place",
                "Business Status",
                "Website",
                "Outcome",
                "Verified Emails",
                "Cached Emails",
                "Checked At",
                "Pages Checked",
                "Failed Pages",
                "Contact Forms",
            ],
        )
        addresses = csv.DictWriter(
            outreach,
            lineterminator="\n",
            fieldnames=[
                "Name",
                "Place ID",
                "Address",
                "Email",
                "Role",
                "Suggested For Allergy Inquiry",
                "Source URLs",
                "Checked At",
                "Website",
            ],
        )
        summary.writeheader()
        addresses.writeheader()
        for file in get_out_files():
            data = json.loads(file.read_text())
            discovery = data.get("email_discovery", {})
            sources = sourced_emails(discovery)
            pages = discovery.get("pages", [])
            # A redirecting Maps CID may differ from the canonical result CID.
            on_list = cached_cid(data) in current or file.name in listed_files
            is_food = bool(food_types & set(data.get("types", []))) or bool(
                data.get("food_place", False)
            )
            legacy = set(data.get("emails", [])) | {data.get("email", "")}
            summary.writerow(
                {
                    "Name": data.get("name", file.stem),
                    "Place ID": data.get("place_id", ""),
                    "On Saved List": on_list,
                    "Food Place": is_food,
                    "Business Status": data.get("business_status", ""),
                    "Website": data.get("website", ""),
                    "Outcome": discovery.get("outcome", "not_checked"),
                    "Verified Emails": " ".join(sorted(sources)),
                    "Cached Emails": " ".join(
                        sorted(
                            e
                            for e in legacy
                            if not bad_email(e)
                            and e not in discovery.get("candidate_sources", {})
                            and e not in discovery.get("excluded_sources", {})
                        )
                    ),
                    "Checked At": discovery.get("browser_checked_at")
                    or discovery.get("checked_at", ""),
                    "Pages Checked": len(pages),
                    "Failed Pages": " | ".join(
                        f"{p['status']}: {p['url']}"
                        for p in pages
                        if p["status"] not in {"ok", "browser_ok"}
                    ),
                    "Contact Forms": " | ".join(discovery.get("contact_forms", [])),
                }
            )
            if (
                not on_list
                or not is_food
                or data.get("business_status") != "OPERATIONAL"
            ):
                continue
            for email, urls in sorted(sources.items()):
                role = email_role(email)
                addresses.writerow(
                    {
                        "Name": data.get("name", file.stem),
                        "Place ID": data.get("place_id", ""),
                        "Address": data.get("formatted_address")
                        or BeautifulSoup(data.get("adr_address", ""), "html.parser")
                        .get_text()
                        .strip(),
                        "Email": email,
                        "Role": role,
                        "Suggested For Allergy Inquiry": role
                        in {"general/unspecified", "allergy/dietary", "reservations"},
                        "Source URLs": " | ".join(urls),
                        "Checked At": discovery.get("browser_checked_at")
                        or discovery.get("checked_at", ""),
                        "Website": data.get("website", ""),
                    }
                )
    export_new_places()
    with (OUT_DIR / "email_candidates_review.csv").open("w", newline="") as out:
        writer = csv.DictWriter(
            out,
            lineterminator="\n",
            fieldnames=[
                "Name",
                "Maps CID",
                "Email",
                "Source URLs",
                "Reason",
                "Review Required",
            ],
        )
        writer.writeheader()
        for file in get_out_files():
            data = json.loads(file.read_text())
            for email, candidate in (
                data.get("email_discovery", {}).get("candidate_sources", {}).items()
            ):
                writer.writerow(
                    {
                        "Name": data.get("name", file.stem),
                        "Maps CID": cached_cid(data),
                        "Email": email,
                        "Source URLs": " | ".join(candidate["urls"]),
                        "Reason": candidate["reason"],
                        "Review Required": True,
                    }
                )
    click.echo(
        f"Email reports: {OUT_DIR / 'email_coverage.csv'}, {OUT_DIR / 'outreach_contacts.csv'}"
    )


def export_new_places() -> None:
    snapshot = OUT_DIR / "maps_saved_list.json"
    if not snapshot.exists():
        return
    document = json.loads(snapshot.read_text())
    with (OUT_DIR / "new_places.csv").open("w", newline="") as out:
        writer = csv.DictWriter(
            out,
            lineterminator="\n",
            fieldnames=[
                "Name",
                "Saved List Name",
                "Maps CID",
                "Place ID",
                "Address",
                "Phone",
                "Website",
                "Business Status",
                "Details Source",
                "API Lookup",
                "Verified Emails",
                "Email Outcome",
            ],
        )
        writer.writeheader()
        for place in document["places"]:
            if place.get("scan_outcome") not in {"added", "browser_verified"}:
                continue
            data = json.loads((OUT_JSON_DIR / place["cache_file"]).read_text())
            discovery = data.get("email_discovery", {})
            writer.writerow(
                {
                    "Name": data.get("name", ""),
                    "Saved List Name": place["list_name"],
                    "Maps CID": place["cid"],
                    "Place ID": data.get("place_id", ""),
                    "Address": data.get("formatted_address", ""),
                    "Phone": data.get("formatted_phone_number", ""),
                    "Website": data.get("website", ""),
                    "Business Status": data.get("business_status", ""),
                    "Details Source": data.get(
                        "details_source", "google_places_legacy"
                    ),
                    "API Lookup": data.get("api_lookup_status", "OK"),
                    "Verified Emails": " ".join(sorted(sourced_emails(discovery))),
                    "Email Outcome": discovery.get("outcome", "not_checked"),
                }
            )


@cli.command()
def email_reports() -> None:
    """Regenerate coverage, new-place, and outreach reports without any network calls."""
    export_email_reports()


@cli.command()
def contacts() -> None:
    csv_out_file = OUT_DIR / "restaraunt_contacts.csv"
    with csv_out_file.open("w", newline="") as csvfile:
        fieldnames = ["Name", "Address", "Phone", "Emails", "Website"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()

        for file in get_out_files():
            with file.open() as f:
                data = json.load(f)

            name = data.get("name", file.stem)
            phone = data.get("formatted_phone_number", "")
            original_emails: list[str] = data.get("emails", [])
            discovery = data.get("email_discovery", {})
            withheld = set(discovery.get("candidate_sources", {})) | set(
                discovery.get("excluded_sources", {})
            )
            emails = " ".join(
                email
                for email in original_emails
                if not bad_email(email) and email not in withheld
            )
            website = data.get("website", "")

            # Extract plain text address from HTML
            address = data.get("formatted_address", "")
            if "adr_address" in data:
                soup = BeautifulSoup(data["adr_address"], "html.parser")
                address = soup.get_text().strip()

            writer.writerow(
                {
                    "Name": name,
                    "Address": address,
                    "Phone": phone,
                    "Emails": emails,
                    "Website": website,
                }
            )

    click.secho(f"Contacts exported to {csv_out_file}", fg="green")


if __name__ == "__main__":
    cli()
