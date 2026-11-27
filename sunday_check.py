#!/usr/bin/env python3
"""Check whether next Wednesday's game has enough players.

Reads the next Futsal IJburg Meetup event: who is going and who is on the
waitlist. If fewer than the target (the event's limit, usually 12) are going,
it suggests players from this season who have not signed up yet and builds a
WhatsApp message asking them to join.

    python3 sunday_check.py            # human-readable summary
    python3 sunday_check.py --json     # for a scheduler that sends the email
"""

from __future__ import annotations

import argparse
from datetime import date as Date, datetime
import json
from pathlib import Path
import sys
from typing import Any

import scrape_meetup as meetup
from make_teams import TeamError, nice_date, normalize, parse_match_file, whatsapp_link

HERE = Path(__file__).resolve().parent
MATCHES = HERE / "matches.txt"
SCHEDULE = HERE / "schedule.txt"
DEFAULT_TARGET = 12
MAX_SUGGESTIONS = 10


def fetch_names(event_id: str, statuses: tuple[str, ...]) -> list[str]:
    """Names of members with one of the given RSVP statuses; may be empty."""
    endpoint = meetup.graphql_url(meetup.DEFAULT_EVENTS_URL)
    _, names = meetup.fetch_registered_players(endpoint, event_id, statuses, allow_empty=True)
    return names


def season_start(schedule: Path) -> str | None:
    """First date in schedule.txt, or None when there is no schedule."""
    if not schedule.is_file():
        return None
    for line in schedule.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def same_person(a: str, b: str) -> bool:
    """Normalized names match, or one is the other's first name(s) ("Manzur" / "Manzur M.")."""
    shorter, longer = sorted((a, b), key=len)
    return longer == shorter or longer.startswith(shorter + " ")


def suggestions(matches_text: str, exclude: list[str], since: str | None) -> list[dict[str, Any]]:
    """Regular players this season who are not going or waitlisted: most matches first."""
    matches, _ = parse_match_file(matches_text)
    excluded = [normalize(n) for n in exclude]
    seen: dict[str, dict[str, Any]] = {}
    for match in matches:  # newest first
        if since and match.date < since:
            continue
        for team in match.teams:
            for name in team.players:
                key = normalize(name)
                if any(same_person(key, other) for other in excluded):
                    continue
                entry = seen.setdefault(key, {"name": name, "last_played": match.date, "matches": 0})
                entry["matches"] += 1
    # regulars first: most matches this season, then most recent
    return sorted(seen.values(), key=lambda e: (e["matches"], e["last_played"]), reverse=True)[:MAX_SUGGESTIONS]


def message(day: str, going: int, target: int, names: list[str], url: str) -> str:
    who = ", ".join(names) if names else "anyone"
    return (f"⚽ Futsal {nice_date(day)}: we're {going}/{target} so far.\n"
            f"{who} - can you join this Wednesday? Sign up here: {url}")


def check(target: int | None) -> dict[str, Any]:
    event = meetup.discover_next_event(meetup.DEFAULT_EVENTS_URL)
    day = datetime.fromisoformat(event["dateTime"].replace("Z", "+00:00")).date().isoformat()
    if day < Date.today().isoformat():  # discover_next_event falls back to the last past event
        raise meetup.ScrapeError(f"No upcoming Meetup event yet (the latest was {day}).")
    limit = target or event.get("maxTickets") or DEFAULT_TARGET
    going = fetch_names(str(event["id"]), ("YES", "ATTENDED"))
    waitlist = fetch_names(str(event["id"]), ("WAITLIST",))
    url = event.get("eventUrl") or meetup.DEFAULT_EVENTS_URL
    enough = len(going) >= limit
    result: dict[str, Any] = {
        "date": day,
        "date_label": nice_date(day),
        "event_url": url,
        "target": limit,
        "going": going,
        "going_count": len(going),
        "waitlist": waitlist,
        "waitlist_count": len(waitlist),
        "missing": max(0, limit - len(going)),
        "enough": enough,
    }
    if not enough:
        picks = suggestions(MATCHES.read_text(encoding="utf-8"), going + waitlist,
                            season_start(SCHEDULE))
        text = message(day, len(going), limit, [p["name"] for p in picks], url)
        result.update(suggested=picks, whatsapp_text=text, whatsapp_link=whatsapp_link(text))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether next Wednesday has enough players.")
    parser.add_argument("--target", type=int, help="players needed (default: the event's limit, else 12)")
    parser.add_argument("--json", action="store_true", help="machine-readable output for a scheduler")
    args = parser.parse_args(argv)
    try:
        result = check(args.target)
    except (meetup.ScrapeError, TeamError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"Futsal {result['date_label']}: {result['going_count']}/{result['target']} going, "
          f"{result['waitlist_count']} on the waitlist.")
    if result["enough"]:
        print("Enough players - nothing to send.")
    else:
        print(f"Short by {result['missing']}. Suggested: " + ", ".join(p["name"] for p in result["suggested"]))
        print(f"WhatsApp: {result['whatsapp_link']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
