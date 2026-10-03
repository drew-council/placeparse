# placeparse

Query saved Google Maps places, extract website emails, and export contacts.
The existing working list is the 339 cached JSON files in
`output/restaraunt_data/`, corresponding to `output/restaraunt_contacts.csv`.
Automatic saved-list extraction is deferred; status refresh does **not** add or
remove places from your Google Maps list.

## Development

```sh
nix develop
uv sync
uv run python placeparse.py --help
uv run python -m unittest discover -s tests
uv run ruff check placeparse.py tests
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

## Original commands

- `query-list`: imports `Takeout/Saved/Want to go.csv` (currently absent).
  Processes every CSV row. Manual Takeout import is optional legacy behavior,
  not required for status refresh.
- `get-emails`: scrapes the cached websites for email addresses.
- `contacts`: regenerates `output/restaraunt_contacts.csv` from cached JSON.

## Credential diagnosis

Console inspection found the project and Places API intact, billing linked,
and no active or recoverable API keys. The old 1Password credential matched the
hardcoded source key and returned `REQUEST_DENIED`. A replacement restricted
key was created in the same project, saved back to the existing 1Password item,
and successfully tested. The Console did not establish who/what removed the
old credential, or whether it originally belonged to this project. Old keys
remain in Git history but are rejected; the replacement is not stored in Git.
