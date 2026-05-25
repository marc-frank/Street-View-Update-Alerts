# Street View Update Alerts

Poll [Google Street View Metadata](https://developers.google.com/maps/documentation/streetview/metadata) for locations you care about and get notified when the panorama ID or image date changes. Runs on a schedule via GitHub Actions — no PC required.

## Setup

### 1. Google Maps API key

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable **Street View Static API** (metadata uses the same API).
3. Create an API key and restrict it to Street View Static API if you like.

Metadata-only requests are [free and do not count against quota](https://developers.google.com/maps/documentation/streetview/usage-and-billing).

### 2. Locations

Coordinates are **not** committed to the repo. For GitHub Actions, store them in the `LOCATIONS_JSON` secret (see step 3). For local runs, copy the example file:

```bash
cp locations.example.json locations.json
```

`locations.json` is gitignored.

**`LOCATIONS_JSON` secret** — paste the full JSON (one line or pretty-printed), for example:

```json
{
  "locations": [
    {
      "id": "home",
      "name": "Home",
      "lat": 52.520008,
      "lng": 13.404954,
      "radius": 50
    }
  ]
}
```

Each entry supports:

| Field | Required | Description |
|-------|----------|-------------|
| `lat`, `lng` | yes | Point to check |
| `name` or `id` | recommended | Label used in alerts and state |
| `radius` | no | Search radius in meters (default API behavior if omitted) |
| `source` | no | `default` or `outdoor` |

### 3. GitHub secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Required | Description |
|--------|----------|-------------|
| `LOCATIONS_JSON` | yes | Full locations JSON (same shape as `locations.example.json`) |
| `GOOGLE_MAPS_API_KEY` | yes | Your Maps API key |
| `SLACK_WEBHOOK_URL` | no* | Incoming Slack webhook |
| `DISCORD_WEBHOOK_URL` | no* | Discord channel webhook |
| `NOTIFY_WEBHOOK_URL` | no* | Generic JSON POST `{"text": "..."}` |
| `SMTP_HOST` | no* | Mail server hostname (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | no | Port (default `587`; use `465` for SSL) |
| `SMTP_USER` | no* | SMTP login / sender account |
| `SMTP_PASSWORD` | no* | SMTP password or [app password](https://support.google.com/accounts/answer/185833) |
| `NOTIFY_EMAIL_TO` | no* | Recipient(s), comma-separated |
| `NOTIFY_EMAIL_FROM` | no | From address (defaults to `SMTP_USER`) |

\* Configure at least one notification channel (Slack, Discord, webhook, or the full email set: `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_TO`). You can enable **multiple channels at once** — all configured channels receive the same alert.

#### Email examples

**Gmail:** use an app password (not your normal Google password).

| Secret | Value |
|--------|-------|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `you@gmail.com` |
| `SMTP_PASSWORD` | your 16-character app password |
| `NOTIFY_EMAIL_TO` | `you@gmail.com` |

**Outlook / Microsoft 365:**

| Secret | Value |
|--------|-------|
| `SMTP_HOST` | `smtp.office365.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `you@outlook.com` |
| `SMTP_PASSWORD` | your account or app password |
| `NOTIFY_EMAIL_TO` | `you@outlook.com` |

### 4. Push to GitHub

Commit `state.json` and the workflow (not `locations.json`). The first scheduled run **records baseline** panorama data and does not alert. Later runs notify when `pano_id` or `date` changes.

`state.json` only stores panorama IDs, dates, and check timestamps — not your coordinates. Use neutral `id` values (e.g. `spot-a`) if you want labels in the repo to stay vague.

Trigger a manual run anytime: **Actions → Check Street View updates → Run workflow**.

## Local test

Use `locations.json`, or set `LOCATIONS_JSON` the same way as in GitHub Actions.

**PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GOOGLE_MAPS_API_KEY = "your_key_here"
$env:SMTP_HOST = "smtp.gmail.com"
$env:SMTP_PORT = "587"
$env:SMTP_USER = "you@gmail.com"
$env:SMTP_PASSWORD = "your_app_password"
$env:NOTIFY_EMAIL_TO = "you@gmail.com"
python check_streetview.py
```

**Command Prompt (`cmd`):**

```bat
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
set GOOGLE_MAPS_API_KEY=your_key_here
set SMTP_HOST=smtp.gmail.com
set SMTP_PORT=587
set SMTP_USER=you@gmail.com
set SMTP_PASSWORD=your_app_password
set NOTIFY_EMAIL_TO=you@gmail.com
python check_streetview.py
```

## Schedule

Default: daily at 09:00 Europe/Berlin (see `.github/workflows/check-streetview.yml`). [GitHub cron syntax](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule)

## How it works

1. For each location, call the metadata endpoint (by lat/lng, not a stored `pano_id`).
2. Compare `pano_id` and `date` to `state.json`.
3. On change, send a notification with a Google Maps panorama link.
4. Commit updated `state.json` so the next run has the latest baseline.
