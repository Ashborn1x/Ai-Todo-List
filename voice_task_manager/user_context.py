from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

REGION_PATTERN = re.compile(r"^[A-Z]{2}$")
COUNTRY_PATTERN = re.compile(r"^[\w .,'’&()/-]{1,64}$")


def build_user_context(raw_context: Any) -> dict[str, str]:
    context = raw_context if isinstance(raw_context, dict) else {}

    try:
        offset_minutes = int(context.get("utc_offset_minutes", 0))
    except (TypeError, ValueError):
        offset_minutes = 0
    offset_minutes = max(-14 * 60, min(14 * 60, offset_minutes))
    local_timezone = timezone(timedelta(minutes=offset_minutes))

    region = str(context.get("region", "")).strip().upper()
    if not REGION_PATTERN.fullmatch(region):
        region = ""

    country = str(context.get("country", "")).strip()
    if not COUNTRY_PATTERN.fullmatch(country):
        country = ""

    local_now = datetime.now(local_timezone)
    return {
        "region": region,
        "country": country,
        "local_datetime": local_now.strftime("%A, %B %d, %Y at %I:%M:%S %p"),
        "local_iso_datetime": local_now.isoformat(timespec="seconds"),
    }


def user_context_instruction(context: dict[str, str]) -> str:
    location_parts = []
    if context["country"]:
        location_parts.append(f"country or region: {context['country']}")
    elif context["region"]:
        location_parts.append(f"country or region code: {context['region']}")

    location = "; ".join(location_parts) or "country or region: not provided"
    return (
        " User country context: "
        f"{location}. "
        f"The user's local date and time at session start is {context['local_datetime']}. "
        f"Its exact ISO 8601 value is {context['local_iso_datetime']}. "
        "Interpret today, tomorrow, weekdays, and spoken times using this local clock. "
        "Use only the provided country-level location. Do not infer or claim to know "
        "the user's city, address, coordinates, or other precise location."
    )
