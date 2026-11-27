# IJburg Futsal

A dependency-free static website for weekly match results, teams, player standings, and a played-together matrix.

The core site is four files:

- `index.html` — page content
- `styles.css` — design
- `script.js` — match parsing and standings
- `matches.txt` — weekly results

Optional player photos live in the `avatars` folder.

## Add a match

Edit [`matches.txt`](matches.txt) and add the newest match at the top:

```text
2026-09-02
Red (5)  : Alex Smorodin, Daniel Bradburn, Osman, Randy Bukasa, Iarik, Marcos
Blue (6) : Andrea, Amine Rhord, Hassan El Azzouzi, Maurizio Perino, Mattia, Tiago Vieira
```

Leave a blank line before the next match. Team names and player counts can vary. Dates must use `YYYY-MM-DD`; scores must be whole numbers; player names must be separated by commas.

The table awards three points for a win and one for a draw. Players are ranked by points, goal difference, goals scored, then name.

The **Together** tab counts how many times every pair of players appeared on the same team. It is calculated automatically from the same match file.

## Import the next Meetup roster

Run the dependency-free scraper to import the registered players from the next
Futsal IJburg Meetup event:

```bash
python3 scrape_meetup.py
```

The script updates that event's dated block in `matches.txt`, or inserts it at
the top if it is not there yet. Existing match results are left unchanged.

## Season schedule

The **Schedule** tab reads [`schedule.txt`](schedule.txt): one game date per line
(`YYYY-MM-DD`). Past dates are crossed out automatically (with the score when
the match is in `matches.txt`) and the next game is highlighted at the top.

## Suggest teams with private ratings

`make_teams.py` suggests three balanced Red/Blue splits for the upcoming player
list in `matches.txt` (or `--players "A, B, ..."`), each with a WhatsApp share
link. It first splits "never play together" pairs, then spreads defenders and
strikers, then evens out total strength from the private tiers, and finally uses
the same result-based checks as the website. Because of the private ratings it
can suggest different teams than the website's team picker.

```bash
python3 make_teams.py --players "Jane Example, John Sample, ..."
python3 make_teams.py --json   # teams and WhatsApp links for a scheduler
python3 -m unittest test_make_teams
```

The ratings are private. Keep them out of this public repository: put them in a
git-ignored `ratings.txt` locally, or in a `PLAYER_RATINGS` secret on a
scheduler. See [`ratings.example.txt`](ratings.example.txt) for the format.

## Check for enough players

`sunday_check.py` reads the next Meetup event and reports how many players are
going and on the waitlist. If fewer than the event's limit (usually 12) are
going, it suggests this season's regular players (season start from
`schedule.txt`) who have not signed up yet, with a WhatsApp message and the
Meetup sign-up link.

```bash
python3 sunday_check.py          # summary
python3 sunday_check.py --json   # for a scheduled email
python3 -m unittest test_sunday_check
```

## Add player photos

Place each photo in the [`avatars`](avatars) folder and name it `<player name>.jpg`. The name must match `matches.txt` exactly—for example, `Daniel Bradburn.jpg`. Square images work best. Missing photos fall back to the player’s initials.

## Preview locally

The page fetches `matches.txt`, so browsers require a small local web server rather than opening `index.html` directly:

```bash
python3 -m http.server 5173
```

Then open <http://localhost:5173>.

## Publish on GitHub Pages

1. Push the repository to GitHub with `main` as its default branch.
2. Open **Settings → Pages** in the repository.
3. Under **Build and deployment**, choose **Deploy from a branch**.
4. Select the `main` branch and the `/(root)` folder, then save.

Every merge to `main` publishes the files directly. There is no installation, build step, or deployment workflow. A weekly pull request only needs to edit `matches.txt`.

The site requests `matches.txt` without using Chrome's HTTP cache. It also uses a
small network-first service worker for the page, stylesheet, script, and match
data, so a normal reload picks up a completed GitHub Pages deployment. Player
photos are revalidated too, while unchanged photos can still use the browser's
cached copy.
