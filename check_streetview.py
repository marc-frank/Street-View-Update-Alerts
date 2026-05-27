#!/usr/bin/env python3
"""Check Google Street View metadata for configured locations and notify on changes."""

from __future__ import annotations

import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
ROOT = Path(__file__).resolve().parent
LOCATIONS_FILE = ROOT / "locations.json"
STATE_FILE = ROOT / "state.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def load_locations() -> dict[str, Any] | None:
    """Load watch list from LOCATIONS_JSON (GitHub Actions) or locations.json (local)."""
    raw = os.environ.get("LOCATIONS_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"LOCATIONS_JSON is not valid JSON: {exc}", file=sys.stderr)
            return None
        if not isinstance(data, dict) or "locations" not in data:
            print('LOCATIONS_JSON must be a JSON object with a "locations" array.', file=sys.stderr)
            return None
        return data

    return load_json(LOCATIONS_FILE, None)


def fetch_metadata(
    api_key: str,
    lat: float,
    lng: float,
    *,
    radius: int | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    params: dict[str, str | int] = {
        "location": f"{lat},{lng}",
        "key": api_key,
    }
    if radius is not None:
        params["radius"] = radius
    if source:
        params["source"] = source

    url = f"{METADATA_URL}?{urlencode(params)}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "OK":
        raise RuntimeError(
            f"Metadata API returned status={data.get('status')!r} "
            f"error_message={data.get('error_message', '')!r}"
        )
    return data


def location_key(entry: dict[str, Any]) -> str:
    return entry.get("id") or entry.get("name") or f"{entry['lat']},{entry['lng']}"


def snapshot_from_metadata(metadata: dict[str, Any]) -> dict[str, str | None]:
    return {
        "pano_id": metadata.get("pano_id"),
        "date": metadata.get("date"),
        "copyright": metadata.get("copyright"),
    }


def snapshots_equal(a: dict[str, str | None], b: dict[str, str | None]) -> bool:
    return a.get("pano_id") == b.get("pano_id") and a.get("date") == b.get("date")


def format_change_message(
    entry: dict[str, Any],
    previous: dict[str, str | None] | None,
    current: dict[str, str | None],
    metadata: dict[str, Any],
) -> str:
    name = entry.get("name") or location_key(entry)
    lat = entry["lat"]
    lng = entry["lng"]
    loc = metadata.get("location", {})
    maps_lat = loc.get("lat", lat)
    maps_lng = loc.get("lng", lng)

    lines = [
        f"Street View update detected: {name}",
        f"Coordinates: {lat}, {lng}",
        f"Maps: https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={maps_lat},{maps_lng}",
        "",
        "Previous:",
        f"  pano_id: {previous.get('pano_id') if previous else '(none)'}",
        f"  date:    {previous.get('date') if previous else '(none)'}",
        "Current:",
        f"  pano_id: {current.get('pano_id')}",
        f"  date:    {current.get('date')}",
    ]
    if current.get("copyright"):
        lines.append(f"  copyright: {current.get('copyright')}")
    return "\n".join(lines)


def format_status_message(
    entry: dict[str, Any],
    current: dict[str, str | None],
    metadata: dict[str, Any],
    status: str,
) -> str:
    name = entry.get("name") or location_key(entry)
    lat = entry["lat"]
    lng = entry["lng"]
    loc = metadata.get("location", {})
    maps_lat = loc.get("lat", lat)
    maps_lng = loc.get("lng", lng)

    lines = [
        f"{name} ({location_key(entry)}): {status}",
        f"  pano_id: {current.get('pano_id')}",
        f"  date:    {current.get('date')}",
        f"  Maps: https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={maps_lat},{maps_lng}",
    ]
    return "\n".join(lines)


def send_slack(webhook_url: str, text: str) -> None:
    response = requests.post(
        webhook_url,
        json={"text": text},
        timeout=30,
    )
    response.raise_for_status()


def send_discord(webhook_url: str, text: str) -> None:
    # Discord content limit is 2000 chars; split if needed.
    chunk_size = 1900
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        response = requests.post(
            webhook_url,
            json={"content": chunk},
            timeout=30,
        )
        response.raise_for_status()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def email_configured() -> bool:
    host = os.environ.get("SMTP_HOST", "").strip()
    to_addrs = os.environ.get("NOTIFY_EMAIL_TO", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = (
        os.environ.get("SMTP_PASSWORD", "").strip()
        or os.environ.get("SMTP_PASS", "").strip()
    )
    return bool(host and to_addrs and user and password)


def send_email(subject: str, body: str) -> None:
    host = os.environ["SMTP_HOST"].strip()
    port = _env_int("SMTP_PORT", 587)
    user = os.environ["SMTP_USER"].strip()
    password = (
        os.environ.get("SMTP_PASSWORD", "").strip()
        or os.environ.get("SMTP_PASS", "").strip()
    )
    to_addrs = [
        addr.strip()
        for addr in os.environ["NOTIFY_EMAIL_TO"].split(",")
        if addr.strip()
    ]
    if not to_addrs:
        raise ValueError("NOTIFY_EMAIL_TO must contain at least one address")

    from_addr = os.environ.get("NOTIFY_EMAIL_FROM", "").strip() or user
    use_ssl = _env_bool("SMTP_USE_SSL", port == 465)
    use_tls = _env_bool("SMTP_USE_TLS", port == 587 and not use_ssl)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = ", ".join(to_addrs)
    message.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                if use_tls:
                    smtp.starttls()
                smtp.login(user, password)
                smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        hint = ""
        if "gmail" in host.lower() or "google" in str(exc).lower():
            hint = (
                " Gmail requires an app password in SMTP_PASSWORD (not your normal "
                "login password). Create one: Google Account → Security → 2-Step "
                "Verification → App passwords."
            )
        raise RuntimeError(f"SMTP login failed for {user!r}.{hint}") from exc


def notify(
    text: str,
    *,
    subject: str = "Street View update detected",
    include_email: bool = True,
) -> None:
    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    generic_url = os.environ.get("NOTIFY_WEBHOOK_URL", "").strip()

    sent = False
    if slack_url:
        send_slack(slack_url, text)
        sent = True
    if discord_url:
        send_discord(discord_url, text)
        sent = True
    if generic_url:
        response = requests.post(
            generic_url,
            json={"text": text},
            timeout=30,
        )
        response.raise_for_status()
        sent = True
    if include_email and email_configured():
        send_email(subject, text)
        sent = True

    if not sent:
        print("No notification channel configured; printing alert:\n")
        print(text)


def email_every_run_enabled() -> bool:
    return _env_bool("EMAIL_EVERY_RUN", False)


def main() -> int:
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        print(
            "GOOGLE_MAPS_API_KEY is required. "
            "For GitHub Actions, add it under Settings → Secrets and variables → Actions.",
            file=sys.stderr,
        )
        return 1

    locations_data = load_locations()
    if not locations_data:
        print(
            "Set the LOCATIONS_JSON secret (GitHub Actions) or create "
            f"{LOCATIONS_FILE.name} from locations.example.json (local).",
            file=sys.stderr,
        )
        return 1

    state: dict[str, Any] = load_json(STATE_FILE, {})
    now = datetime.now(timezone.utc).isoformat()
    changes: list[str] = []
    statuses: list[str] = []
    errors: list[str] = []
    state_changed = False

    for entry in locations_data["locations"]:
        key = location_key(entry)
        try:
            metadata = fetch_metadata(
                api_key,
                float(entry["lat"]),
                float(entry["lng"]),
                radius=entry.get("radius"),
                source=entry.get("source"),
            )
            current = snapshot_from_metadata(metadata)
            previous = state.get(key)

            prev_snapshot = None
            if isinstance(previous, dict):
                prev_snapshot = {
                    "pano_id": previous.get("pano_id"),
                    "date": previous.get("date"),
                }

            is_first_run = prev_snapshot is None
            changed = not is_first_run and not snapshots_equal(prev_snapshot, current)

            state[key] = {
                **current,
                "last_checked": now,
            }
            state_changed = True

            if changed:
                status = "UPDATED"
                changes.append(
                    format_change_message(entry, prev_snapshot, current, metadata)
                )
            else:
                status = "initialized" if is_first_run else "unchanged"

            statuses.append(format_status_message(entry, current, metadata, status))
            print(f"[{key}] {status} — pano_id={current.get('pano_id')} date={current.get('date')}")

        except Exception as exc:  # noqa: BLE001 — collect per-location errors
            msg = f"[{key}] error: {exc}"
            print(msg, file=sys.stderr)
            errors.append(msg)

    if state_changed:
        save_json(STATE_FILE, state)

    email_each_run = email_every_run_enabled()

    if email_each_run and email_configured():
        report_lines = [
            f"Checked at {now}",
            "",
            "\n\n".join(statuses) if statuses else "(no locations checked)",
        ]
        if errors:
            report_lines.extend(["", "Errors:", "\n".join(errors)])
        if changes:
            report_lines.extend(["", "Changes:", "", "\n\n---\n\n".join(changes)])

        subject = (
            "Street View update detected"
            if changes
            else "Street View check (no changes)"
        )
        send_email(subject, "\n".join(report_lines))

    if changes:
        change_body = "\n\n---\n\n".join(changes)
        notify(change_body, include_email=not email_each_run)
    elif not errors and not email_each_run:
        print("No Street View changes detected.")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
