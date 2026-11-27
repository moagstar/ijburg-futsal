#!/usr/bin/env python3
"""Suggest balanced Red/Blue futsal teams and WhatsApp share links.

Uses the match history in matches.txt plus an optional *private* ratings table:

    # name | position | tier | never with
    Jane Doe | defender | 2 | John Roe, Max Moe

- position: defender, striker or allrounder
- tier: 1 (best) .. 4, decimals allowed (e.g. 2.5 or 3.75)
- never with: comma-separated names who must not be in the same team

The ratings are read from the PLAYER_RATINGS environment variable (a secret on a
scheduler), otherwise from ratings.txt next to this script. ratings.txt is git-ignored: never commit real ratings to this public repo.
Ratings are never written to the WhatsApp message.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import date as Date
from itertools import combinations
import os
from pathlib import Path
import re
from typing import Literal
import sys
import unicodedata
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
DEFAULT_MATCHES = HERE / "matches.txt"
DEFAULT_RATINGS = HERE / "ratings.txt"

TEAM_PATTERN = re.compile(r"^(.*?)\s*\((\d+)\)\s*:\s*(.+)$")
POSITIONS = {"defender": "defender", "striker": "striker", "allrounder": "allrounder",
             "all-rounder": "allrounder", "": "allrounder"}
BEST_TIER, WORST_TIER = 1, 4
DEFAULT_TIER = (BEST_TIER + WORST_TIER) / 2  # used for brand-new players nobody rated
MIN_PLAYERS = 4
# Results are only trusted gradually: a player's own numbers are blended with a
# typical value as if they had this many extra average matches. With 2 matches
# their own results count for 1/3, with 8 matches for 2/3, and so on.
SHRINK_MATCHES = 4


class TeamError(ValueError):
    """Raised for invalid input files or impossible requests."""


def normalize(name: str) -> str:
    """Compare names ignoring case, accents and extra spaces."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


def clean_player_name(name: str) -> str:
    return re.sub(r"^Badge for\s+", "", name, flags=re.IGNORECASE).strip()


# --- match history (same rules as script.js) ---------------------------------

@dataclass
class Team:
    name: str
    score: int
    players: list[str]


@dataclass
class Match:
    date: str
    teams: tuple[Team, Team]


def parse_team(line: str) -> Team | None:
    found = TEAM_PATTERN.match(line)
    if not found:
        return None
    players = [p.strip() for p in found.group(3).split(",") if p.strip()]
    return Team(found.group(1).strip(), int(found.group(2)), players)


def parse_match_file(text: str) -> tuple[list[Match], tuple[str, list[str]] | None]:
    matches: list[Match] = []
    upcoming: tuple[str, list[str]] | None = None
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [ln.strip() for ln in block.splitlines()]
        lines = [ln for ln in lines if ln and not ln.startswith("#")]
        if not lines:
            continue
        day, *entries = lines
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise TeamError(f"Invalid date: {day}")
        teams = [parse_team(e) for e in entries]
        if len(entries) == 2 and all(teams):
            matches.append(Match(day, (teams[0], teams[1])))
            continue
        if upcoming:
            raise TeamError("Only one upcoming player list is supported.")
        players = [clean_player_name(e) for e in entries if clean_player_name(e)]
        if not players:
            raise TeamError(f"No players listed for {day}.")
        upcoming = (day, players)
    matches.sort(key=lambda m: m.date, reverse=True)
    return matches, upcoming


@dataclass
class History:
    name: str = ""
    played: int = 0
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0


def player_history(matches: list[Match]) -> dict[str, History]:
    table: dict[str, History] = {}
    for match in matches:
        first, second = match.teams
        for team, opponent in ((first, second), (second, first)):
            for name in team.players:
                h = table.setdefault(normalize(name), History(name=name))
                h.played += 1
                h.goals_for += team.score
                h.goals_against += opponent.score
                if team.score == opponent.score:
                    h.points += 1
                elif team.score > opponent.score:
                    h.points += 3
    return table


def played_together(matches: list[Match]) -> dict[frozenset[str], int]:
    counts: dict[frozenset[str], int] = {}
    for match in matches:
        for team in match.teams:
            names = [normalize(n) for n in team.players]
            for a, b in combinations(names, 2):
                key = frozenset((a, b))
                counts[key] = counts.get(key, 0) + 1
    return counts


# --- private ratings ---------------------------------------------------------

@dataclass
class Rating:
    name: str
    position: str
    tier: float
    never_with: set[str] = field(default_factory=set)  # normalized names


def parse_ratings(text: str) -> tuple[dict[str, Rating], list[str]]:
    """Parse the ratings table. A bad line is skipped (with a warning), never fatal.

    Accepted per line:  name | tier   or   name | position | tier [| never with]
    Returns the ratings and the warnings (line numbers and reasons only).
    """
    ratings: dict[str, Rating] = {}
    warnings: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 2:  # short form: name | tier
            parts = [parts[0], "", parts[1]]
        if len(parts) < 3 or not parts[0]:
            warnings.append(f"line {number} skipped: expected 'name | tier' or 'name | position | tier'")
            continue
        position = POSITIONS.get(parts[1].casefold())
        if position is None:
            warnings.append(f"line {number} skipped: position must be defender, striker or allrounder")
            continue
        try:
            tier = float(parts[2].replace(",", "."))
        except ValueError:
            tier = 0.0
        if not BEST_TIER <= tier <= WORST_TIER:
            warnings.append(f"line {number} skipped: tier must be a number from {BEST_TIER} to {WORST_TIER} (e.g. 2, 2.5 or 3.75)")
            continue
        key = normalize(parts[0])
        if key in ratings:
            warnings.append(f"line {number}: name already listed earlier, using this line")
        never = {normalize(n) for n in (parts[3] if len(parts) > 3 else "").split(",") if n.strip()}
        ratings[key] = Rating(parts[0], position, tier, never)
    return ratings, warnings


def load_ratings() -> tuple[dict[str, Rating], list[str], str]:
    """Return (ratings, warnings, where they came from)."""
    secret = os.environ.get("PLAYER_RATINGS")
    if secret and secret.strip():
        return *parse_ratings(secret), "PLAYER_RATINGS secret"
    if DEFAULT_RATINGS.is_file():
        return *parse_ratings(DEFAULT_RATINGS.read_text(encoding="utf-8")), DEFAULT_RATINGS.name
    return {}, [], "none (match results only)"


# --- players for this week ---------------------------------------------------

TierSource = Literal["rated", "estimated", "default"]


@dataclass
class Player:
    name: str
    key: str
    position: str
    tier: float
    tier_source: TierSource
    played: int
    ppm: float
    gdpm: float
    gfpm: float
    never_with: set[str]

    @property
    def newcomer(self) -> bool:
        return self.played == 0

    @property
    def unknown(self) -> bool:
        return self.tier_source == "default"


def quantile(values: list[float], position: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * position
    lower, upper = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def tier_quantile(tier: float) -> float:
    """Best tier -> 87.5th percentile of known players, worst -> 12.5th (clamped 0..1)."""
    span = WORST_TIER - BEST_TIER
    return min(1.0, max(0.0, 0.125 + (WORST_TIER - tier) / span * 0.75))


def build_players(
    names: list[str], history: dict[str, History], ratings: dict[str, Rating]
) -> list[Player]:
    known = [h for h in history.values() if h.played]
    stats = {
        "ppm": [h.points / h.played for h in known],
        "gdpm": [(h.goals_for - h.goals_against) / h.played for h in known],
        "gfpm": [h.goals_for / h.played for h in known],
    }

    def typical(tier: float) -> tuple[float, float, float]:
        q = tier_quantile(tier)
        return tuple(quantile(stats[k], q) for k in ("ppm", "gdpm", "gfpm"))

    seen: set[str] = set()
    players: list[Player] = []
    for name in names:
        key = normalize(name)
        if key in seen:
            continue
        seen.add(key)
        h = history.get(key, History())
        rating = ratings.get(key)
        if rating:
            tier, source, position = rating.tier, "rated", rating.position
        else:
            tier, source, position = DEFAULT_TIER, "default", "allrounder"
        prior = typical(tier)

        if h.played:  # blend own results with the typical value (few matches -> mostly typical)
            raw = (h.points / h.played, (h.goals_for - h.goals_against) / h.played,
                   h.goals_for / h.played)
            weight = h.played / (h.played + SHRINK_MATCHES)
            ppm, gdpm, gfpm = (weight * r + (1 - weight) * t for r, t in zip(raw, prior))
            if not rating:
                # Not rated yet: estimate the tier from (blended) results.
                share_below = sum(v < ppm for v in stats["ppm"]) / max(len(stats["ppm"]), 1)
                estimate = WORST_TIER - (WORST_TIER - BEST_TIER) * share_below
                tier, source = round(estimate * 2) / 2, "estimated"
        else:  # no history: typical numbers for that tier
            ppm, gdpm, gfpm = prior
        players.append(Player(
            name=h.name or (rating.name if rating else name),
            key=key, position=position, tier=tier, tier_source=source,
            played=h.played, ppm=ppm, gdpm=gdpm, gfpm=gfpm,
            never_with=set(rating.never_with) if rating else set(),
        ))
    # make "never with" symmetric for this roster, including unrated players
    by_key = {p.key: p for p in players}
    for p in players:
        for other in p.never_with:
            if other in by_key:
                by_key[other].never_with.add(p.key)
    return players


# --- balancing ---------------------------------------------------------------

@dataclass
class Metrics:
    strength: float  # sum of (5 - tier): tier 1 = 4 points, 2.5 = 2.5, 4 = 1
    defenders: int
    strikers: int
    unknown: int
    newcomers: int
    ppm: float
    gdpm: float
    gfpm: float
    appearances: int
    familiar: int


def team_metrics(team: list[Player], together: dict[frozenset[str], int]) -> Metrics:
    n = len(team)
    familiar = sum(together.get(frozenset((a.key, b.key)), 0) for a, b in combinations(team, 2))
    return Metrics(
        strength=sum(WORST_TIER + 1 - p.tier for p in team),
        defenders=sum(p.position == "defender" for p in team),
        strikers=sum(p.position == "striker" for p in team),
        unknown=sum(p.unknown for p in team),
        newcomers=sum(p.newcomer for p in team),
        ppm=sum(p.ppm for p in team) / n,
        gdpm=sum(p.gdpm for p in team) / n,
        gfpm=sum(p.gfpm for p in team) / n,
        appearances=sum(p.played for p in team),
        familiar=familiar,
    )


def conflicts(team: list[Player]) -> int:
    return sum(b.key in a.never_with for a, b in combinations(team, 2))


@dataclass
class Candidate:
    red: list[Player]
    blue: list[Player]
    red_m: Metrics
    blue_m: Metrics
    clashes: int
    score: tuple[float, ...]


def candidate_score(red: Metrics, blue: Metrics, clashes: int) -> tuple[float, ...]:
    """Lower is better; compared in order, like script.js."""
    # Total strength, not the average: with an odd number of players the team
    # with one player fewer gets stronger players to make up for it.
    return (
        clashes,                                   # 1. "never play together"
        abs(red.defenders - blue.defenders)        # 2. spread defenders and strikers
        + abs(red.strikers - blue.strikers),
        abs(red.strength - blue.strength),         # 3. equal total strength
        abs(red.unknown - blue.unknown),           # --- current site logic ---
        abs(red.ppm - blue.ppm),
        abs(red.gdpm - blue.gdpm),
        abs(red.gfpm - blue.gfpm),
        abs(red.newcomers - blue.newcomers),
        abs(red.appearances - blue.appearances),
        abs(red.familiar - blue.familiar),
        red.familiar + blue.familiar,
    )


def rounded(score: tuple[float, ...]) -> tuple[float, ...]:
    """Round away float noise so equally good splits compare equal."""
    return tuple(round(v, 9) for v in score)


def suggest(
    players: list[Player], together: dict[frozenset[str], int], count: int = 3
) -> list[Candidate]:
    n = len(players)
    if n < MIN_PLAYERS:
        raise TeamError(f"Need at least {MIN_PLAYERS} players, got {n}.")
    red_size = (n + 1) // 2  # with an odd number Red gets the extra player
    if n % 2 == 0:  # fix the first player in Red so mirror images are not repeated
        anchor, others = players[0], players[1:]
        reds = ([anchor, *rest] for rest in combinations(others, red_size - 1))
    else:
        reds = (list(c) for c in combinations(players, red_size))

    candidates: list[Candidate] = []
    for red in reds:
        red_keys = {p.key for p in red}
        blue = [p for p in players if p.key not in red_keys]
        red_m, blue_m = team_metrics(red, together), team_metrics(blue, together)
        clashes = conflicts(red) + conflicts(blue)
        candidates.append(Candidate(red, blue, red_m, blue_m, clashes,
                                    candidate_score(red_m, blue_m, clashes)))

    def names(c: Candidate) -> str:
        return "\0".join(p.key for p in c.red)

    candidates.sort(key=lambda c: (rounded(c.score), names(c)))
    best = rounded(candidates[0].score)
    optimal = [c for c in candidates if rounded(c.score) == best]
    selected = [optimal.pop(0)]

    def distance(a: Candidate, b: Candidate) -> int:
        reds = {p.key for p in a.red}
        return sum(p.key not in reds for p in b.red)

    while optimal and len(selected) < count:  # pick equally good but different splits
        optimal.sort(key=lambda c: (-min(distance(c, s) for s in selected), names(c)))
        selected.append(optimal.pop(0))
    for c in candidates:
        if len(selected) >= count:
            break
        if c not in selected:
            selected.append(c)
    return selected


# --- output ------------------------------------------------------------------

def nice_date(iso: str) -> str:
    d = Date.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b}"


def whatsapp_text(day: str, candidate: Candidate) -> str:
    red = ", ".join(sorted((p.name for p in candidate.red), key=normalize))
    blue = ", ".join(sorted((p.name for p in candidate.blue), key=normalize))
    return f"⚽ Futsal {nice_date(day)}\n🔴 Red: {red}\n🔵 Blue: {blue}"


def whatsapp_link(text: str) -> str:
    return "https://wa.me/?text=" + quote(text, safe="")


def balance_note(c: Candidate) -> str:
    r, b = c.red_m, c.blue_m
    parts = [
        f"strength {r.strength:g} vs {b.strength:g}",
        f"def {r.defenders}/{b.defenders}",
        f"str {r.strikers}/{b.strikers}",
        f"form {r.ppm:.2f} vs {b.ppm:.2f}",
    ]
    if c.clashes:
        parts.append(f"⚠ {c.clashes} 'never together' pair(s) could not be split")
    return " · ".join(parts)


def report(day: str, players: list[Player], suggestions: list[Candidate],
           source: str, warnings: list[str]) -> str:
    lines = [f"Futsal {nice_date(day)} · {len(players)} players · ratings: {source}", ""]
    for warning in warnings:  # line numbers and reasons only, never the line itself
        lines.append(f"⚠ ratings {warning}")
    if warnings:
        lines.append("")
    for index, c in enumerate(suggestions, start=1):
        text = whatsapp_text(day, c)
        lines.append(f"Option {index}")
        lines.extend(text.splitlines()[1:3])
        lines.append(f"({balance_note(c)})")
        lines.append(f"Send: {whatsapp_link(text)}")
        lines.append("")
    unrated = [p for p in players if p.tier_source != "rated"]
    if unrated:
        lines.append("Not rated (add them to the ratings):")
        for p in unrated:
            how = (f"estimated tier {p.tier:g} from {p.played} matches" if p.tier_source == "estimated"
                   else "new, counted as average")
            lines.append(f"- {p.name}: {how}")
    return "\n".join(lines).rstrip() + "\n"


def as_json(day: str, suggestions: list[Candidate], warnings: list[str]) -> str:
    """Structured output for a scheduler that writes the email: only the teams."""
    options = []
    for c in suggestions:
        text = whatsapp_text(day, c)
        options.append({
            "red": sorted((p.name for p in c.red), key=normalize),
            "blue": sorted((p.name for p in c.blue), key=normalize),
            "whatsapp_text": text,
            "whatsapp_link": whatsapp_link(text),
        })
    return json.dumps({"date": day, "ratings_warnings": warnings, "options": options},
                      ensure_ascii=False, indent=2)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suggest balanced Red/Blue futsal teams.")
    parser.add_argument("--players", help="comma-separated names (default: the upcoming list in matches.txt)")
    parser.add_argument("--json", action="store_true", help="machine-readable output for a scheduler")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        matches, upcoming = parse_match_file(DEFAULT_MATCHES.read_text(encoding="utf-8"))
        if args.players:
            names = [n.strip() for n in args.players.split(",") if n.strip()]
            day = upcoming[0] if upcoming else Date.today().isoformat()
        elif upcoming:
            day, names = upcoming
        else:
            raise TeamError("No upcoming player list in matches.txt; pass --players.")
        ratings, warnings, source = load_ratings()
        players = build_players(names, player_history(matches), ratings)
        suggestions = suggest(players, played_together(matches))
    except (TeamError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    if args.json:
        print(as_json(day, suggestions, warnings))
    else:
        print(report(day, players, suggestions, source, warnings), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
