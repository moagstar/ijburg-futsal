const teamPattern = /^(.*?)\s*\((\d+)\)\s*:\s*(.+)$/;

function parseMatches(text) {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));

  if (lines.length % 3 !== 0) {
    throw new Error("Each match needs a date and two team lines.");
  }

  const matches = [];
  for (let index = 0; index < lines.length; index += 3) {
    const date = lines[index];
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      throw new Error(`Invalid date: ${date}`);
    }

    const teams = [lines[index + 1], lines[index + 2]].map((line) => {
      const result = line.match(teamPattern);
      if (!result) throw new Error(`Invalid team line: ${line}`);

      return {
        name: result[1].trim(),
        score: Number(result[2]),
        players: result[3].split(",").map((name) => name.trim()).filter(Boolean),
      };
    });

    matches.push({ date, teams });
  }

  return matches.sort((a, b) => b.date.localeCompare(a.date));
}

function calculateStandings(matches) {
  const table = new Map();

  function getPlayer(name) {
    if (!table.has(name)) {
      table.set(name, {
        name, played: 0, won: 0, drawn: 0, lost: 0,
        goalsFor: 0, goalsAgainst: 0, goalDifference: 0, points: 0,
      });
    }
    return table.get(name);
  }

  matches.forEach(({ teams: [first, second] }) => {
    const draw = first.score === second.score;

    [first, second].forEach((team, teamIndex) => {
      const opponent = teamIndex === 0 ? second : first;
      team.players.forEach((name) => {
        const player = getPlayer(name);
        player.played += 1;
        player.goalsFor += team.score;
        player.goalsAgainst += opponent.score;

        if (draw) {
          player.drawn += 1;
          player.points += 1;
        } else if (team.score > opponent.score) {
          player.won += 1;
          player.points += 3;
        } else {
          player.lost += 1;
        }
      });
    });
  });

  return [...table.values()]
    .map((player) => ({
      ...player,
      goalDifference: player.goalsFor - player.goalsAgainst,
    }))
    .sort((a, b) =>
      b.points - a.points ||
      b.goalDifference - a.goalDifference ||
      b.goalsFor - a.goalsFor ||
      a.name.localeCompare(b.name),
    );
}

function formatDate(date) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(`${date}T12:00:00`));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderTeamName(name) {
  const colour = name.trim().toLowerCase();
  if (colour === "red" || colour === "blue") {
    return `<span class="jersey jersey-${colour}" role="img" aria-label="${colour} team"></span>`;
  }
  return escapeHtml(name);
}

function renderAvatar(name) {
  const initials = name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
  const fileName = encodeURIComponent(`${name}.jpg`);

  return `
    <span class="avatar" aria-hidden="true">
      <img src="avatars/${fileName}" alt="" loading="lazy">
      <span class="avatar-fallback">${escapeHtml(initials)}</span>
    </span>
  `;
}

function pairKey(first, second) {
  return [first, second].sort((a, b) => a.localeCompare(b)).join("\u0000");
}

function calculatePlayedTogether(matches) {
  const counts = new Map();

  matches.forEach(({ teams }) => {
    teams.forEach(({ players }) => {
      for (let first = 0; first < players.length; first += 1) {
        for (let second = first + 1; second < players.length; second += 1) {
          const key = pairKey(players[first], players[second]);
          counts.set(key, (counts.get(key) || 0) + 1);
        }
      }
    });
  });

  return counts;
}

function renderTogetherMatrix(matches, players) {
  const counts = calculatePlayedTogether(matches);
  const highestCount = Math.max(1, ...counts.values());
  const names = players.map(({ name }) => name);
  const headerCells = names.map((name) => `
    <th scope="col" title="${escapeHtml(name)}">
      <span class="matrix-column-player">
        ${renderAvatar(name)}
        <span>${escapeHtml(name.split(/\s+/)[0])}</span>
      </span>
    </th>
  `).join("");

  const rows = names.map((rowName) => {
    const cells = names.map((columnName) => {
      if (rowName === columnName) return '<td class="matrix-diagonal">—</td>';
      const count = counts.get(pairKey(rowName, columnName)) || 0;
      const heat = count / highestCount;
      return `<td class="matrix-count" style="--heat: ${heat}" title="${escapeHtml(rowName)} and ${escapeHtml(columnName)}: ${count} matches">${count}</td>`;
    }).join("");

    return `
      <tr>
        <th scope="row"><span class="player-cell">${renderAvatar(rowName)}<span>${escapeHtml(rowName)}</span></span></th>
        ${cells}
      </tr>
    `;
  }).join("");

  document.querySelector("#together-matrix").innerHTML = `
    <table class="matrix-table" aria-label="Matches played together">
      <thead><tr><th scope="col">Player</th>${headerCells}</tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function render(matches) {
  const standings = calculateStandings(matches);

  document.querySelector("#standings-body").innerHTML = standings
    .map((player, index) => `
      <tr>
        <td class="position"><span>${index + 1}</span></td>
        <th scope="row">
          <span class="player-cell">${renderAvatar(player.name)}<span>${escapeHtml(player.name)}</span></span>
        </th>
        <td>${player.played}</td>
        <td>${player.won}</td>
        <td>${player.drawn}</td>
        <td>${player.lost}</td>
        <td>${player.goalDifference > 0 ? "+" : ""}${player.goalDifference}</td>
        <td class="points">${player.points}</td>
      </tr>
    `)
    .join("");

  document.querySelector("#results-list").innerHTML = matches
    .map(({ date, teams }, index) => `
      <article class="match${index === 0 ? " latest-match" : ""}">
        <div class="match-meta">
          <time datetime="${date}">${formatDate(date)}</time>
          ${index === 0 ? '<span class="latest-label">Latest</span>' : ""}
        </div>
        <div class="teams">
          <div>
            <h3>${renderTeamName(teams[0].name)}</h3>
            <ul class="player-list">
              ${teams[0].players.map((name) => `<li>${renderAvatar(name)}<span>${escapeHtml(name)}</span></li>`).join("")}
            </ul>
          </div>
          <div class="match-score" aria-label="${teams[0].score} to ${teams[1].score}">
            <strong>${teams[0].score}</strong><span>–</span><strong>${teams[1].score}</strong>
          </div>
          <div class="team-b">
            <h3>${renderTeamName(teams[1].name)}</h3>
            <ul class="player-list">
              ${teams[1].players.map((name) => `<li>${renderAvatar(name)}<span>${escapeHtml(name)}</span></li>`).join("")}
            </ul>
          </div>
        </div>
      </article>
    `)
    .join("");

  renderTogetherMatrix(matches, standings);

  document.querySelectorAll(".avatar img").forEach((image) => {
    image.addEventListener("error", () => image.parentElement.classList.add("avatar-missing"));
  });

  document.querySelector("#status").remove();
}

const tabs = [...document.querySelectorAll('[role="tab"]')];
const panels = [...document.querySelectorAll('[role="tabpanel"]')];

function selectTab(tabName, updateHash = true) {
  tabs.forEach((tab) => {
    const selected = tab.dataset.tab === tabName;
    tab.setAttribute("aria-selected", selected);
    tab.tabIndex = selected ? 0 : -1;
  });
  panels.forEach((panel) => {
    panel.hidden = panel.id !== tabName;
  });
  if (updateHash) history.replaceState(null, "", `#${tabName}`);
}

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectTab(tab.dataset.tab));
  tab.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const nextTab = tabs[(index + direction + tabs.length) % tabs.length];
    nextTab.focus();
    selectTab(nextTab.dataset.tab);
  });
});

const requestedTab = location.hash.slice(1);
selectTab(tabs.some((tab) => tab.dataset.tab === requestedTab) ? requestedTab : "standings", false);

fetch("matches.txt")
  .then((response) => {
    if (!response.ok) throw new Error("Could not load matches.txt.");
    return response.text();
  })
  .then(parseMatches)
  .then((matches) => {
    if (!matches.length) throw new Error("No matches found.");
    render(matches);
  })
  .catch((error) => {
    console.error(error);
    document.querySelector("#status").textContent =
      "The match file has a formatting error. Please check the latest entry.";
  });
