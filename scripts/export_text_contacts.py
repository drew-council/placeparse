"""Offline, current-list food contacts; excludes visited/permanently closed places.

Publication/form inspection is not ownership, delivery, or submission testing.
Social profiles and third-party email leads are explicitly not verified channels.
"""

import csv
import json
from collections import Counter

import placeparse
from email_discovery import email_role

FOOD_TYPES = {"restaurant", "food", "cafe", "bakery", "meal_takeaway", "meal_delivery"}
GENERAL_ROLES = {"general/unspecified", "reservations", "allergy/dietary"}


def export() -> Counter[str]:
    placeparse.current_list_cids()  # Refuse an incomplete membership snapshot.
    snapshot = json.loads((placeparse.OUT_DIR / "maps_saved_list.json").read_text())
    counts = Counter()
    fields = [
        "Name",
        "Maps CID",
        "Address",
        "Business Status",
        "General Inquiry Emails",
        "Email Source URLs",
        "General Contact Forms",
        "Other Purpose Emails",
        "Limited Purpose Forms",
        "Social Profile Leads (DMs Unverified)",
        "Candidate Emails (Unverified)",
        "Candidate Warnings",
        "Text Contact Outcome",
        "Website",
        "Phone",
        "Checked At",
        "Deeper Email Investigation",
        "Email Investigation Sources",
        "Email Investigation Queries",
        "Why No General Email Accepted",
        "Remaining Email Avenues",
        "Research Notes",
    ]
    output = placeparse.OUT_DIR / "food_text_contacts.csv"
    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for member in snapshot["places"]:
            data = json.loads(
                (placeparse.OUT_JSON_DIR / member["cache_file"]).read_text()
            )
            if not placeparse.consider_for_outreach(data):
                continue
            if data.get("business_status") == "CLOSED_PERMANENTLY":
                continue
            if not (
                FOOD_TYPES.intersection(data.get("types", []))
                or data.get("food_place")
                or data.get("text_contact_discovery", {}).get("food_service_evidence")
            ):
                continue
            counts["eligible"] += 1
            discovery = data.get("email_discovery", {})
            sources = placeparse.sourced_emails(discovery)
            roles = {
                e: discovery.get("role_overrides", {}).get(e, email_role(e))
                for e in sources
            }
            general = {
                e: urls for e, urls in sources.items() if roles[e] in GENERAL_ROLES
            }
            research = data.get("text_contact_discovery", {})
            investigation = research.get("email_investigation", {})
            channels = [
                c
                for c in research.get("channels", [])
                if c.get("business_match_confirmed")
            ]
            forms = sorted(
                {
                    c["url"]
                    for c in channels
                    if c["kind"] == "contact_form" and c["purpose"] == "general inquiry"
                }
            )
            limited = sorted(
                {
                    f"{c['purpose']}: {c['url']}"
                    for c in channels
                    if c["purpose"] != "general inquiry"
                }
            )
            profiles = sorted({p["url"] for p in research.get("social_profiles", [])})
            candidates = discovery.get("candidate_sources", {})
            if general and forms:
                outcome = "email_and_form"
            elif general:
                outcome = "email"
            elif forms:
                outcome = "general_contact_form"
            elif limited or sources:
                outcome = "limited_purpose_only"
            elif candidates:
                outcome = "unverified_email_leads_only"
            elif profiles:
                outcome = "social_profile_leads_only"
            else:
                outcome = "no_text_route_found_in_checked_sources"
            counts[outcome] += 1
            counts["sourced_email_places"] += bool(sources)
            counts["general_email_places"] += bool(general)
            counts["general_form_places"] += bool(forms)
            counts["email_or_general_form_places"] += bool(general or forms)
            counts["social_profile_lead_places"] += bool(profiles)
            counts["candidate_email_places"] += bool(candidates)
            notes = [
                "No messages sent or forms submitted. Mailbox delivery and form submission are untested."
            ]
            if profiles:
                notes.append(
                    "Social links are leads, not proof that private messaging is enabled; login may be required."
                )
            if sources:
                notes.append(
                    "Email roles are routing heuristics, not confirmed dietary/allergy contacts."
                )
            for email in general:
                publication = discovery.get("publication_evidence", {}).get(email, {})
                if publication.get("note"):
                    notes.append(f"{email}: {publication['note']}")
            if research.get("errors") or investigation.get("errors"):
                notes.append(
                    "Some lookups failed or were blocked; missing contacts are not proof none exist."
                )
            writer.writerow(
                {
                    "Name": data["name"],
                    "Maps CID": member["cid"],
                    "Address": data.get("formatted_address", ""),
                    "Business Status": data.get("business_status", ""),
                    "General Inquiry Emails": " | ".join(sorted(general)),
                    "Email Source URLs": " | ".join(
                        sorted({u for urls in general.values() for u in urls})
                    ),
                    "General Contact Forms": " | ".join(forms),
                    "Other Purpose Emails": " | ".join(
                        f"{e} ({roles[e]})" for e in sorted(sources) if e not in general
                    ),
                    "Limited Purpose Forms": " | ".join(limited),
                    "Social Profile Leads (DMs Unverified)": " | ".join(profiles),
                    "Candidate Emails (Unverified)": " | ".join(sorted(candidates)),
                    "Candidate Warnings": " | ".join(
                        f"{e}: {v['reason']}" for e, v in sorted(candidates.items())
                    ),
                    "Text Contact Outcome": outcome,
                    "Website": data.get("website", ""),
                    "Phone": data.get("formatted_phone_number", ""),
                    "Checked At": investigation.get("parent_reviewed_at")
                    or research.get("checked_at")
                    or discovery.get("browser_checked_at")
                    or discovery.get("checked_at", ""),
                    "Deeper Email Investigation": investigation.get("outcome", ""),
                    "Email Investigation Sources": " | ".join(
                        investigation.get("inspected_urls", [])
                    ),
                    "Email Investigation Queries": " | ".join(
                        q["query"] for q in investigation.get("queries", [])
                    ),
                    "Why No General Email Accepted": (
                        investigation.get("no_general_email_reason", "")
                        if not general
                        else ""
                    ),
                    "Remaining Email Avenues": " | ".join(
                        investigation.get("remaining_avenues", [])
                    ),
                    "Research Notes": " ".join(notes),
                }
            )
    print(f"{output}: {dict(counts)}")
    return counts


if __name__ == "__main__":
    export()
