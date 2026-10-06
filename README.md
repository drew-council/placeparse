# placeparse

Query saved Google Maps places, extract website emails, and export contacts.
Cached details live in `output/restaraunt_data/`, with contacts exported to
`output/restaraunt_contacts.csv`. The live source is Angie's shared **Want to go**
list (369 entries in the final snapshot), captured from Maps with agent-browser.
The original 368-entry capture was UI-validated; a final observed-response recheck
found SILK ROAD BITES added, with every earlier CID retained. Old records are preserved even if absent from that list;
none of these commands modifies your Google Maps saved lists.

## Development

```sh
nix develop
uv sync
uv run python placeparse.py --help
uv run python -m unittest discover -s tests
uv run ruff check placeparse.py email_discovery.py scripts tests
ty check
```

The small flake follows the nix-project-template input/devShell convention and
provides Python 3.13, uv, Ruff, ty, and gcloud. Run `nix fmt` to format the
flake once it is tracked. Use `nix develop path:.` before new flake files are tracked by Git.
1Password CLI (`op`) uses the host's authenticated desktop integration rather
than a separate shell installation.

## Credentials (1Password)

Use the personal account, **not** the work gcloud account. The existing
`google-places` API credential is in the personal **Private** vault. Read it once
per shell, then reuse the environment variable (each `op` call may prompt):

```sh
export GOOGLE_MAPS_API_KEY="$(op read --account my.1password.com 'op://Private/google-places/credential')"
```

Never commit keys, copy them into commands, or enable shell tracing (`set -x`)
while loading credentials. `unset GOOGLE_MAPS_API_KEY` when finished.

The existing Cloud project is `placeparse-464303`. Legacy **Places API** is
already enabled and billing is linked. The replacement `placeparse-local` key
is restricted to that API. It has no IP restriction because this is a local CLI
with potentially changing egress; restrict it to known IPs if deployed.
Google API requests may incur charges. New projects should use Places API (New)
instead; this repo still uses the already-enabled legacy API.

## Refresh the existing list's operating status

```sh
# Smoke test (writes a separate sample report)
uv run python placeparse.py refresh-status --limit 1
# All existing cached places
uv run python placeparse.py refresh-status
```

Only `place_id` and `business_status` are requested. Successful responses update
cached status and a UTC `business_status_checked_at` timestamp, preserving
emails, phones, websites, and all other cached fields. The full report is
`output/place_status.csv`; samples use `output/place_status_sample.csv`.
It includes previous/current status and per-place fetch outcomes.

Failed lookups retain the original JSON and have a blank current status in the
report—`NOT_FOUND` does **not** prove closure. Authentication/quota errors stop
the run immediately. Other unverified places are recorded, and the command
exits nonzero after finishing. Reports are flushed per place, so partial
results survive interruption. A rerun refreshes all selected places again.
The contacts CSV is left unchanged; use the status report alongside it.

## Capture the live list and scan new places

In the same logged-in Chromium, open Saved → Angie's shared **Want to go** list.
Use the personal account, not the work account. The browser session must remain
attached to that list tab:

```sh
uv run python scripts/capture_maps_list.py \
  --session placeparse-user-chromium-5ebd98fa0364 --cdp 9222 --expected-count 369
uv run python placeparse.py scan-new-places output/maps_saved_list.json --limit 1
uv run python placeparse.py scan-new-places output/maps_saved_list.json
```

Update `--expected-count` to match the UI next time. Capture reads the complete
list response that Maps already requested in this browser session. It validates
the list ID, title, count, unique CIDs, and overlap with displayed list cards,
then writes `output/maps_saved_list.json`. It does not reconstruct private RPCs,
export auth, or store raw headers/account metadata. Reopen the list if its
response has expired. Maps UI/response shapes may change; unexpected shapes
fail instead of silently importing an incomplete list.

Some saved CIDs may no longer work with the legacy Places API. Keep these
failures explicit; do not infer closure. A browser-verified record can retain
its saved `maps_cid`, observed canonical Maps URL, phone/site, and UI status
without inventing an API `place_id`. Bodega Truck and Corgi Jianbing LIC were
verified this way after legacy `NOT_FOUND` responses; the latter has a new Maps
listing at the same Hunter Street address. Their status evidence is marked as
Maps UI rather than API data. SILK ROAD BITES was added during the final
recheck without another credential read or paid API call. Its name, CID, real
published Places ID, address, phone, website, and scheduled reopening text came
from the place response Maps had already requested. Its source is explicitly
`google_maps_observed_response`, with API lookup `NOT_REQUESTED`. Final Maps
panels did not render; the snapshot records response-only validation rather
than claiming a new UI count.

The final snapshot reconciles 267 existing records, 99 API additions, and three
browser-derived additions (102 new places). All 72 older off-list records remain,
for 441 cached records. `output/place_status.csv` is the original 339-place status
refresh, not a report of the subsequent additions; see `output/new_places.csv`
and `output/email_coverage.csv` for their statuses and provenance.

New-place scanning checks cached CIDs and canonical Places IDs, not names.
Only missing places incur detail requests. Names cannot overwrite existing
records; filename collisions get a CID suffix. New details include address,
phone, website, type, and business status. API billing may apply (including
contact-data fields). Membership reconciliation never deletes old records.

## Discover emails for allergy-inquiry outreach

```sh
uv run python placeparse.py get-emails
# Resume a completed/partially completed scan without repeating website requests
uv run python placeparse.py get-emails --only-unchecked
# Render public websites when the HTTP pass couldn't find a suitable contact
uv run python -m scripts.check_rendered_emails \
  --session placeparse-emails-user-chromium --cdp 9222
uv run python placeparse.py email-reports  # offline report regeneration
uv run python placeparse.py contacts
```

Every selected cached place is checked, even if it already has an email.
Discovery follows up to six same-host contact/about/reservation/FAQ/location
links, records source URLs and UTC check times, and reads mailto links, public
text, common obfuscation, and Cloudflare's public email encoding. Four websites
are processed concurrently with per-site time/size/page limits; robots exclusions
are respected. Requests use no browser cookies or API credentials, validate
public URLs/redirects, and do not submit forms or send email. Redirects to an
unrelated hostname require review rather than attributing that site's emails to
the restaurant. Known vendor/publisher mailboxes and template addresses are
excluded. Existing exclusions and manual-review candidates survive repeat scans
and cannot silently reappear as outreach recipients.

The rendered second pass uses a separate pinned tab in the same Chromium,
checks up to three observed homepage/contact links, and closes only its own tab.
It skips robots-excluded sites and authenticated social/ordering platforms,
records load failures/challenges, and does not bypass them. It is a fallback,
not an exhaustive search of every page or proof of absence.

Reports (all regenerated by `email-reports`, except the legacy contacts CSV):
- `output/new_places.csv`: all 102 additions, phone/address/site, business status,
  detail provenance, API outcome, and sourced email coverage.
- `output/email_candidates_review.csv`: published but unverified leads,
  with source URLs and reasons; **not included as outreach recipients**.
- `output/email_coverage.csv`: every cached place, current-list membership,
  sourced/cached emails, pages checked, failures, and contact-form URLs.
- `output/outreach_contacts.csv`: one row per sourced email for **operational food
  places currently on the shared list**. Includes role and source evidence;
  reviewed purpose overrides take precedence over mailbox-name heuristics.
  General/reservation/dietary addresses are suggested over careers/press/events,
  privacy/legal, class, and website-accessibility recipients. Publication/routing
  notes and a false `Delivery Tested` flag accompany each row.
- `output/restaraunt_contacts.csv`: all preserved cache records, including old
  emails that were not reverified, except explicitly excluded/quarantined
  mailboxes. Raw historical emails remain in JSON (use the sourced outreach
  report instead of the legacy CSV for outreach).

“Found” means published on a checked page, not deliverability, permission to
email, or a confirmed allergy contact. Role suggestions are heuristics and need
review. “Not found on checked pages” is **not** proof no email exists: JavaScript,
images/PDFs, unlinked pages, stale/delivery-only websites, and blocked/failed fetches
can hide one. Failures are tracked as incomplete lookups, never silent absence.
Legacy cached addresses are preserved separately from newly sourced evidence.
`unverified_only` means a published lead needs ownership/purpose confirmation;
those addresses are isolated in the manual-review report. The `Verified Emails`
columns mean source-backed publication, not verified deliverability or a confirmed
staff recipient. Form detection is heuristic: an email-entry form can be a
newsletter or booking signup rather than an inquiry channel.

The initial HTTP pass covered all cached records, followed by 135 rendered
checks. A subsequent browser investigation checked all 194 initially unsourced
food venues, retried search-challenged results through an independent public
search provider, and manually checked additional scope/branch cases. No challenge
was bypassed. After the deeper email-focused pass described below, there are
225 current-list places with sourced emails, including 61 of the additions. These remain bounded checks, not a guarantee that every
existing email has been found. Confirm the recipient and appropriate channel
before sending personal allergy information.

No allergy details are shared and no outreach is sent by these commands.

## Current-list food venues: email and text inquiry routes

```sh
uv run python -m scripts.export_text_contacts  # offline; no credentials/browser
```

`output/food_text_contacts.csv` is the food-scoped contact worksheet. It excludes
permanently closed places and non-food establishments, preserves temporary-closure
status, and includes cafes, bakeries, food carts, and meal-service venues. Generic
Maps tags are not enough to exclude a food business: separately retained
`food_service_evidence` includes Teado Tea Shop (Maps identifies a tea house with
snacks) and Donovan's Pub (its own site publishes a kitchen/menu). Bar-only places
without food evidence are not selected for food outreach.

After the deeper email-focused pass, among **349 eligible venues**:

- **217** have sourced emails; **199** have a suggested general/reservation/dietary
  mailbox, up from 166. Source-specific purpose review overrides heuristics;
  these are not confirmed allergy contacts.
- **51** have inspected general-inquiry forms (not newsletter/review/order forms).
- **238** have a suggested general email **or** general-inquiry form: 187 email-only,
  39 form-only, and 12 with both.
- The other 111 are 45 with only social-profile leads, 17 with unverified email
  leads, 11 with limited-purpose channels only, and 38 with no text route found
  in the checked sources. This is not a claim that no other channel exists.

The worksheet separates general routes, press/careers/event/legal mailboxes,
reservation-request forms, unverified email candidates, and social-profile leads.
It retains URLs, check times, errors, recipient-routing caveats, and source notes.
The candidate review report contains 37 addresses for 29 venues; they are not
outreach recipients. The email-only operational-food report contains 283 sourced
addresses for 215 venues (237 suggested addresses) and does not include forms.

Forms were inspected for actual free-text inquiry fields, **not submitted or
end-to-end tested**. Social-profile links (133 venues have leads) do not prove
private messaging is enabled or delivered and may require login. Directory
review/profile-update forms, unrelated business mailboxes, and website technical
support are not promoted as general restaurant-inquiry routes. Sister-venue/group
contacts are explicitly labeled where relevant; confirm routing to the saved
branch before discussing medical information.

The per-place `text_contact_discovery` evidence is retained separately from the
older HTTP/rendered email crawl. All original place details and historical email
addresses are preserved. No paid API calls or credential reads were needed for
this follow-up. The earlier browser pass ran in foreground batches after its
initial background sweep was stopped.

The subsequent email-focused investigation covered **all 183 venues lacking an
accepted general email**, including the 35 previously form-only venues. Authorized
GLM Flash/high workers researched non-overlapping restaurant packets in isolated
headless browser sessions; only the parent accepted contacts and changed caches.
The parent supplied additional public search leads and independently inspected
publications or the original browser tool evidence. Some worker artifacts also
report public HTTP/PDF-text checks; their method notes are retained rather than
claiming every check was browser-only. No credentials, paid Places API requests,
messages, form submissions, logins, or challenge bypasses were used.

Each assigned record retains `text_contact_discovery.email_investigation`: source
URLs, queries, concrete blockers, remaining avenues, original worker proposals,
parent decisions, model, artifact hash, and actual completion/review timestamps.
The worksheet includes corresponding deeper-investigation columns; the original
HTTP crawl counts remain separate. `output/email_investigation_summary.json`
records the scope and final coverage. Website-accessibility/privacy/class/press
mailboxes are not promoted to general contacts merely because their names are
`contact`, `info`, `support`, or `hello`. Hidden payment/form-routing addresses,
old archives, parked/template domains, and unresolved branch identity remain
withheld. Social profiles remain leads only, not successful contacts.

## Other commands

- `query-list`: imports `Takeout/Saved/Want to go.csv` (currently absent).
  Processes every CSV row. Manual Takeout import is optional legacy behavior,
  not required for status refresh.
- `contacts`: regenerates `output/restaraunt_contacts.csv` from cached JSON.

## Credential diagnosis

Console inspection found the project and Places API intact, billing linked,
and no active or recoverable API keys. The old 1Password credential matched the
hardcoded source key and returned `REQUEST_DENIED`. A replacement restricted
key was created in the same project, saved back to the existing 1Password item,
and successfully tested. The Console did not establish who/what removed the
old credential, or whether it originally belonged to this project. Old keys
remain in Git history but are rejected; the replacement is not stored in Git.
