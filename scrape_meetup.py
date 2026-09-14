#!/usr/bin/env python3
"""Write the next Futsal IJburg Meetup roster to matches.txt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


DEFAULT_EVENTS_URL = "https://www.meetup.com/futsal-ijburg/events/"
DEFAULT_OUTPUT = Path(__file__).with_name("matches.txt")
USER_AGENT = "Mozilla/5.0 (compatible; ijburg-futsal-roster/1.0)"
RSVPS_PER_PAGE = 100


def ssl_context() -> ssl.SSLContext:
    default_paths = ssl.get_default_verify_paths()
    if default_paths.cafile:
        return ssl.create_default_context()
    system_bundle = Path("/etc/ssl/cert.pem")
    if system_bundle.is_file():
        return ssl.create_default_context(cafile=system_bundle)
    return ssl.create_default_context()


SSL_CONTEXT = ssl_context()

EVENT_RSVPS_QUERY = """
query RegisteredPlayers(
  $eventId: ID!
  $first: Int
  $after: String
  $filter: RsvpFilter
) {
  event(id: $eventId) {
    id
    title
    dateTime
    rsvps(first: $first, after: $after, filter: $filter) {
      totalCount
      edges {
        node {
          member {
            id
            name
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


class ScrapeError(RuntimeError):
    """Raised when Meetup does not return the expected data."""


class NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_next_data = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.in_next_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_next_data:
            self.in_next_data = False

    def handle_data(self, data: str) -> None:
        if self.in_next_data:
            self.parts.append(data)

    @property
    def next_data(self) -> str:
        return "".join(self.parts)


def request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"

    try:
        with urlopen(
            Request(url, data=data, headers=headers), timeout=30, context=SSL_CONTEXT
        ) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ScrapeError(f"Could not retrieve JSON from {url}: {error}") from error


def request_text(url: str) -> str:
    try:
        with urlopen(
            Request(url, headers={"User-Agent": USER_AGENT}),
            timeout=30,
            context=SSL_CONTEXT,
        ) as response:
            return response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError) as error:
        raise ScrapeError(f"Could not retrieve {url}: {error}") from error


def parse_next_data(html: str) -> dict[str, Any]:
    parser = NextDataParser()
    parser.feed(html)
    if not parser.next_data:
        raise ScrapeError("Meetup page did not contain __NEXT_DATA__ JSON")
    try:
        return json.loads(parser.next_data)
    except json.JSONDecodeError as error:
        raise ScrapeError("Meetup's __NEXT_DATA__ was not valid JSON") from error


def discover_next_event(events_url: str) -> dict[str, Any]:
    page = parse_next_data(request_text(events_url))
    try:
        cache = page["props"]["pageProps"]["__APOLLO_STATE__"]
    except (KeyError, TypeError) as error:
        raise ScrapeError("Meetup page did not contain its Apollo event data") from error

    group_prefix = events_url.rstrip("/") + "/"
    events = [
        value
        for key, value in cache.items()
        if key.startswith("Event:")
        and isinstance(value, dict)
        and str(value.get("eventUrl", "")).startswith(group_prefix)
        and value.get("dateTime")
    ]
    if not events:
        raise ScrapeError(f"No events found at {events_url}")

    def event_time(event: dict[str, Any]) -> datetime:
        return datetime.fromisoformat(event["dateTime"].replace("Z", "+00:00"))

    now = datetime.now(timezone.utc)
    upcoming = [
        event
        for event in events
        if event.get("status") == "ACTIVE" and event_time(event) >= now
    ]
    return min(upcoming, key=event_time) if upcoming else max(events, key=event_time)


def graphql_url(events_url: str) -> str:
    parsed = urlsplit(events_url)
    return f"{parsed.scheme}://{parsed.netloc}/gql2"


def fetch_registered_players(endpoint: str, event_id: str) -> tuple[dict[str, Any], list[str]]:
    players: list[str] = []
    seen_member_ids: set[str] = set()
    after: str | None = None
    event: dict[str, Any] | None = None

    while True:
        payload = {
            "operationName": "RegisteredPlayers",
            "query": EVENT_RSVPS_QUERY,
            "variables": {
                "eventId": event_id,
                "first": RSVPS_PER_PAGE,
                "after": after,
                "filter": {"rsvpStatus": ["YES", "ATTENDED"]},
            },
        }
        result = request_json(endpoint, payload)
        if result.get("errors"):
            message = "; ".join(
                error.get("message", "Unknown error") for error in result["errors"]
            )
            raise ScrapeError(f"Meetup GraphQL error: {message}")

        try:
            event = result["data"]["event"]
            rsvps = event["rsvps"]
            for edge in rsvps["edges"]:
                member = edge["node"]["member"]
                member_id = str(member["id"])
                name = member["name"].strip()
                if name and member_id not in seen_member_ids:
                    seen_member_ids.add(member_id)
                    players.append(name)
            page_info = rsvps["pageInfo"]
        except (KeyError, TypeError, AttributeError) as error:
            raise ScrapeError("Meetup returned an unexpected RSVP response") from error

        if not page_info["hasNextPage"]:
            break
        after = page_info.get("endCursor")
        if not after:
            raise ScrapeError("Meetup indicated another RSVP page but returned no cursor")

    if event is None or not players:
        raise ScrapeError(f"No registered players found for event {event_id}")
    return event, players


def update_matches(output: Path, event_date: str, players: list[str]) -> None:
    roster = "\n".join([event_date, *players])
    existing = output.read_text(encoding="utf-8") if output.exists() else ""
    block_pattern = re.compile(
        rf"(?m)^{re.escape(event_date)}\n.*?(?=\n{{2,}}|\Z)",
        re.DOTALL,
    )

    if block_pattern.search(existing):
        updated = block_pattern.sub(roster, existing, count=1)
    elif existing:
        comment_match = re.match(r"((?:#[^\n]*\n)+\n?)", existing)
        insert_at = comment_match.end() if comment_match else 0
        prefix = existing[:insert_at]
        suffix = existing[insert_at:].lstrip("\n")
        updated = f"{prefix}{roster}\n\n{suffix}"
    else:
        updated = f"{roster}\n"

    output.write_text(updated.rstrip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape the next Futsal IJburg Meetup roster into matches.txt."
    )
    parser.add_argument("--events-url", default=DEFAULT_EVENTS_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        listed_event = discover_next_event(args.events_url)
        event, players = fetch_registered_players(
            graphql_url(args.events_url), str(listed_event["id"])
        )
        event_date = datetime.fromisoformat(
            event["dateTime"].replace("Z", "+00:00")
        ).date().isoformat()
        update_matches(args.output, event_date, players)
    except (ScrapeError, KeyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {len(players)} players for {event_date} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
