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
