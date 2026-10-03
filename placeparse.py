import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
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
    emails = set()
    # find mailto: links
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a[href^=mailto]"):
        href = a.get("href", "")
        if not isinstance(href, str):
            continue
        addr = href.split(":", 1)[-1].split("?")[0]
        if EMAIL_RE.fullmatch(addr):
            emails.add(addr)
    # also run regex on the raw HTML just in case
    emails |= set(EMAIL_RE.findall(html))
    return emails


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
def get_emails() -> None:
    """Attempt to get the email address for each restaraunt and add to the json data"""
    for file in tqdm(get_out_files()):
        click.secho("\n" + file.name, fg="blue", italic=True)
        with file.open() as f:
            data = json.load(f)

        name = data.get("name", file.stem)
        click.secho(name, fg="blue", bold=True)
        if data.get("email") or data.get("emails"):
            click.secho(f"Email(s) already exists for {name}", fg="yellow")
            continue

        website = data.get("website")
        if website:
            click.secho(f"Website found: {website}")
        else:
            click.secho(f"No website found for {name}", fg="red")
            continue

        try:
            resp = requests.get(website, timeout=60)
            resp.raise_for_status()
        except requests.RequestException:
            click.secho(f"Error fetching website {website} for {name}", fg="red")
            continue

        emails = list(extract_emails_from_html(resp.text))
        if not emails:
            click.secho(f"No emails found for {name}", fg="yellow")
            continue
        click.secho("Email(s) found:\n", fg="green")
        rich.print(emails)

        data["emails"] = emails
        with file.open("w") as f:
            json.dump(data, f, indent=2)


def bad_email(email: str) -> bool:
    bad_email_domains = [
        "example.com",
        "test.com",
        "invalid.com",
        "wixpress.com",
        "sentry.io",
        "mystore.com",
        ".js",
    ]
    return any(email.endswith(domain) for domain in bad_email_domains)


@cli.command()
def contacts() -> None:
    csv_out_file = OUT_DIR / "restaraunt_contacts.csv"
    with csv_out_file.open("w", newline="") as csvfile:
        fieldnames = ["Name", "Address", "Phone", "Emails", "Website"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for file in get_out_files():
            with file.open() as f:
                data = json.load(f)

            name = data.get("name", file.stem)
            phone = data.get("formatted_phone_number", "")
            original_emails: list[str] = data.get("emails", [])
            emails = " ".join(
                email for email in original_emails if not bad_email(email)
            )
            website = data.get("website", "")

            # Extract plain text address from HTML
            address = ""
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
