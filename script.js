const teamPattern = /^(.*?)\s*\((\d+)\)\s*:\s*(.+)$/;

function parseTeam(line) {
  const result = line.match(teamPattern);
  if (!result) return null;
  return {
    name: result[1].trim(),
    score: Number(result[2]),
    players: result[3].split(",").map((name) => name.trim()).filter(Boolean),
  };
}

function cleanPlayerName(name) {
  return name.replace(/^Badge for\s+/i, "").trim();
}

function parseMatchFile(text) {
  const matches = [];
  let upcoming = null;
  const blocks = text.trim().split(/\r?\n\s*\r?\n/);

  blocks.forEach((block) => {
    const lines = block
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"));
    if (!lines.length) return;

    const [date, ...entries] = lines;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      throw new Error(`Invalid date: ${date}`);
    }

    const teams = entries.map(parseTeam);
    if (entries.length === 2 && teams.every(Boolean)) {
      matches.push({ date, teams });
      return;
    }

    if (upcoming) throw new Error("Only one upcoming player list is supported.");
    const players = entries.map(cleanPlayerName).filter(Boolean);
    if (!players.length) throw new Error(`No players listed for ${date}.`);
    upcoming = { date, players };
  });

  return {
    matches: matches.sort((a, b) => b.date.localeCompare(a.date)),
    upcoming,
  };
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

const lineupState = {
  matches: [],
  profiles: new Map(),
  selected: new Set(),
  together: new Map(),
  visibleSuggestions: 3,
};

function quantile(values, position) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * position;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
}

function calculateBenchmarks() {
  const known = [...lineupState.profiles.values()].filter((player) => !player.newcomer);
  const fields = ["pointsPerMatch", "goalDifferencePerMatch", "goalsForPerMatch"];
  return Object.fromEntries(fields.map((field) => [
    field,
    {
      developing: quantile(known.map((player) => player[field]), .25),
      typical: quantile(known.map((player) => player[field]), .5),
      strong: quantile(known.map((player) => player[field]), .75),
    },
  ]));
}

function playerStrength(player, benchmarks) {
  if (!player.newcomer) return player;
  const estimate = player.estimate === "unknown" ? "typical" : player.estimate;
  return {
    ...player,
    pointsPerMatch: benchmarks.pointsPerMatch[estimate],
    goalDifferencePerMatch: benchmarks.goalDifferencePerMatch[estimate],
    goalsForPerMatch: benchmarks.goalsForPerMatch[estimate],
  };
}

function lineupMetrics(names, benchmarks) {
  const players = names.map((name) => playerStrength(lineupState.profiles.get(name), benchmarks));
  const average = (field) => players.reduce((sum, player) => sum + player[field], 0) / players.length;
  let familiarLinks = 0;
  for (let first = 0; first < names.length; first += 1) {
    for (let second = first + 1; second < names.length; second += 1) {
      familiarLinks += lineupState.together.get(pairKey(names[first], names[second])) || 0;
    }
  }
  return {
    pointsPerMatch: average("pointsPerMatch"),
    goalDifferencePerMatch: average("goalDifferencePerMatch"),
    goalsForPerMatch: average("goalsForPerMatch"),
    appearances: players.reduce((sum, player) => sum + player.played, 0),
    newcomers: players.filter((player) => player.newcomer).length,
    unknownNewcomers: players.filter((player) => player.newcomer && player.estimate === "unknown").length,
    familiarLinks,
  };
}

function combinations(values, size, start = 0, prefix = [], output = []) {
  if (prefix.length === size) {
    output.push([...prefix]);
    return output;
  }
  for (let index = start; index <= values.length - (size - prefix.length); index += 1) {
    prefix.push(values[index]);
    combinations(values, size, index + 1, prefix, output);
    prefix.pop();
  }
  return output;
}

function candidateScore(candidate) {
  const { redMetrics: red, blueMetrics: blue } = candidate;
  return [
    Math.abs(red.unknownNewcomers - blue.unknownNewcomers),
    Math.abs(red.pointsPerMatch - blue.pointsPerMatch),
    Math.abs(red.goalDifferencePerMatch - blue.goalDifferencePerMatch),
    Math.abs(red.goalsForPerMatch - blue.goalsForPerMatch),
    Math.abs(red.newcomers - blue.newcomers),
    Math.abs(red.appearances - blue.appearances),
    Math.abs(red.familiarLinks - blue.familiarLinks),
    red.familiarLinks + blue.familiarLinks,
  ];
}

function compareScores(first, second) {
  for (let index = 0; index < first.length; index += 1) {
    if (Math.abs(first[index] - second[index]) > 1e-9) return first[index] - second[index];
  }
  return 0;
}

function lineupDistance(first, second) {
  const firstRed = new Set(first.red);
  return second.red.reduce((distance, name) => distance + (firstRed.has(name) ? 0 : 1), 0);
}

function generateSuggestions(names, count = 3) {
  const benchmarks = calculateBenchmarks();
  const teamSize = names.length / 2;
  const [anchor, ...others] = names;
  const candidates = combinations(others, teamSize - 1).map((redOthers) => {
    const red = [anchor, ...redOthers];
    const redNames = new Set(red);
    const blue = names.filter((name) => !redNames.has(name));
    const candidate = {
      red,
      blue,
      redMetrics: lineupMetrics(red, benchmarks),
      blueMetrics: lineupMetrics(blue, benchmarks),
    };
    candidate.score = candidateScore(candidate);
    return candidate;
  });

  candidates.sort((first, second) =>
    compareScores(first.score, second.score) ||
    first.red.join("\u0000").localeCompare(second.red.join("\u0000")),
  );
  const optimal = candidates.filter((candidate) => compareScores(candidate.score, candidates[0].score) === 0);
  const selected = [optimal.shift()];

  while (optimal.length && selected.length < count) {
    optimal.sort((first, second) => {
      const firstDistance = Math.min(...selected.map((choice) => lineupDistance(first, choice)));
      const secondDistance = Math.min(...selected.map((choice) => lineupDistance(second, choice)));
      return secondDistance - firstDistance || first.red.join("\u0000").localeCompare(second.red.join("\u0000"));
    });
    selected.push(optimal.shift());
  }

  for (const candidate of candidates) {
    if (selected.length >= count) break;
    if (!selected.includes(candidate)) selected.push(candidate);
  }
  return selected;
}

function wireAvatarFallbacks(scope = document) {
  scope.querySelectorAll(".avatar img").forEach((image) => {
    image.addEventListener("error", () => image.parentElement.classList.add("avatar-missing"), { once: true });
  });
}

function newcomerEstimateOptions(selected) {
  return [
    ["unknown", "Unknown"],
    ["developing", "Developing"],
    ["typical", "Typical"],
    ["strong", "Strong"],
  ].map(([value, label]) => `<option value="${value}"${selected === value ? " selected" : ""}>${label}</option>`).join("");
}

function renderPlayerPicker() {
  const picker = document.querySelector("#player-picker");
  const players = [...lineupState.profiles.values()].sort((first, second) => {
    const selectedDifference = Number(lineupState.selected.has(second.name)) - Number(lineupState.selected.has(first.name));
    const newcomerDifference = Number(second.newcomer) - Number(first.newcomer);
    return selectedDifference || newcomerDifference;
  });
  picker.innerHTML = players.map((player) => `
    <div class="picker-player${lineupState.selected.has(player.name) ? " is-selected" : ""}">
      <label>
        <input type="checkbox" value="${escapeHtml(player.name)}"${lineupState.selected.has(player.name) ? " checked" : ""}>
        ${renderAvatar(player.name)}
        <span class="picker-player-copy">
          <strong>${escapeHtml(player.name)}</strong>
          <small>${player.newcomer ? "No match history" : `${player.played} played · ${player.pointsPerMatch.toFixed(2)} PPM`}</small>
        </span>
      </label>
      ${player.newcomer ? `
        <span class="new-badge">New</span>
        <label class="estimate-control">
          <span class="sr-only">Expected level for ${escapeHtml(player.name)}</span>
          <select data-player="${escapeHtml(player.name)}">${newcomerEstimateOptions(player.estimate)}</select>
        </label>
      ` : ""}
    </div>
  `).join("");
  wireAvatarFallbacks(picker);
  updateSelectionState();
}

function updateSelectionState(message = "") {
  const count = lineupState.selected.size;
  document.querySelector("#selection-count").textContent = `${count} selected`;
  const guidance = document.querySelector("#lineup-guidance");

  if (message) guidance.textContent = message;
  else if (count < 10) guidance.textContent = `Select ${10 - count} more for a 10-player game.`;
  else if (count === 10) guidance.textContent = "Showing balanced teams of 5.";
  else if (count === 11) guidance.textContent = "Select one more, or remove one player.";
  else guidance.textContent = "Showing balanced teams of 6.";
}

function formatMetricPair(first, second, signed = false) {
  const format = (value) => `${signed && value >= 0 ? "+" : ""}${value.toFixed(2)}`;
  return `${format(first)} / ${format(second)}`;
}

function sortPlayerNames(players) {
  return [...players].sort((first, second) => first.localeCompare(second));
}

function renderSuggestedTeam(name, players) {
  const sortedPlayers = sortPlayerNames(players);
  return `
    <div class="suggested-team ${name.toLowerCase()}-team">
      <h4>${renderTeamName(name)}</h4>
      <ul>
        ${sortedPlayers.map((player) => `<li>${renderAvatar(player)}<span>${escapeHtml(player)}</span></li>`).join("")}
      </ul>
    </div>
  `;
}

function renderSuggestions(suggestions) {
  const container = document.querySelector("#lineup-suggestions");
  const cards = suggestions.map((suggestion, index) => {
    const red = suggestion.redMetrics;
    const blue = suggestion.blueMetrics;
    return `
      <article class="suggestion-card">
        <div class="suggestion-header">
          <div>
            <span>Option ${index + 1}</span>
            <strong>${suggestion.red.length} vs ${suggestion.blue.length}</strong>
          </div>
          <button type="button" class="copy-lineup" data-suggestion="${index}">Copy teams</button>
        </div>
        <div class="suggested-teams">
          ${renderSuggestedTeam("Red", suggestion.red)}
          ${renderSuggestedTeam("Blue", suggestion.blue)}
        </div>
        <dl class="balance-summary">
          <div><dt>Avg PPM</dt><dd>${formatMetricPair(red.pointsPerMatch, blue.pointsPerMatch)}</dd></div>
          <div><dt>Avg GD/match</dt><dd>${formatMetricPair(red.goalDifferencePerMatch, blue.goalDifferencePerMatch, true)}</dd></div>
          <div><dt>Avg goals/match</dt><dd>${formatMetricPair(red.goalsForPerMatch, blue.goalsForPerMatch)}</dd></div>
          <div><dt>Played together</dt><dd>${red.familiarLinks} / ${blue.familiarLinks}</dd></div>
        </dl>
      </article>
    `;
  }).join("");
  container.innerHTML = `${cards}<button class="more-lineups" type="button">More options</button>`;
  container.dataset.suggestions = JSON.stringify(suggestions.map(({ red, blue }) => ({
    red: sortPlayerNames(red),
    blue: sortPlayerNames(blue),
  })));
  wireAvatarFallbacks(container);
}

async function copyLineup(button) {
  const suggestions = JSON.parse(document.querySelector("#lineup-suggestions").dataset.suggestions || "[]");
  const suggestion = suggestions[Number(button.dataset.suggestion)];
  if (!suggestion) return;
  const text = `Red: ${suggestion.red.join(", ")}\nBlue: ${suggestion.blue.join(", ")}`;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    document.body.append(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
  button.textContent = "Copied";
  setTimeout(() => { button.textContent = "Copy teams"; }, 1400);
}

function initializeLineupBuilder(matches, standings, upcoming) {
  lineupState.matches = matches;
  lineupState.together = calculatePlayedTogether(matches);
  lineupState.profiles.clear();
  lineupState.selected.clear();

  standings.forEach((player) => lineupState.profiles.set(player.name, {
    ...player,
    newcomer: false,
    estimate: "recorded",
    pointsPerMatch: player.points / player.played,
    goalDifferencePerMatch: player.goalDifference / player.played,
    goalsForPerMatch: player.goalsFor / player.played,
  }));

  (upcoming?.players || []).forEach((name) => {
    if (!lineupState.profiles.has(name)) {
      lineupState.profiles.set(name, {
        name,
        played: 0,
        newcomer: true,
        estimate: "unknown",
      });
    }
    lineupState.selected.add(name);
  });
  renderPlayerPicker();
  refreshSuggestions();
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

function render(matches, upcoming) {
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

  wireAvatarFallbacks();
  initializeLineupBuilder(matches, standings, upcoming);

  document.querySelector("#status")?.remove();
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

function resetSuggestions() {
  const container = document.querySelector("#lineup-suggestions");
  container.removeAttribute("data-suggestions");
  container.innerHTML = `
    <div class="empty-suggestions">
      <span aria-hidden="true">10 / 12</span>
      <p>Your balanced team suggestions will appear here.</p>
    </div>
  `;
}

function refreshSuggestions(resetCount = true) {
  if (resetCount) lineupState.visibleSuggestions = 3;
  const names = [...lineupState.profiles.keys()].filter((name) => lineupState.selected.has(name));
  if (names.length !== 10 && names.length !== 12) {
    resetSuggestions();
    return;
  }
  renderSuggestions(generateSuggestions(names, lineupState.visibleSuggestions));
}

document.querySelector("#player-picker").addEventListener("change", (event) => {
  const checkbox = event.target.closest('input[type="checkbox"]');
  if (checkbox) {
    if (checkbox.checked && lineupState.selected.size >= 12) {
      checkbox.checked = false;
      updateSelectionState("Twelve is the maximum. Remove someone before adding another player.");
      return;
    }
    if (checkbox.checked) lineupState.selected.add(checkbox.value);
    else lineupState.selected.delete(checkbox.value);
    checkbox.closest(".picker-player").classList.toggle("is-selected", checkbox.checked);
    updateSelectionState();
    refreshSuggestions();
    return;
  }

  const estimate = event.target.closest("select[data-player]");
  if (estimate) {
    lineupState.profiles.get(estimate.dataset.player).estimate = estimate.value;
    refreshSuggestions();
  }
});

document.querySelector("#new-player-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.querySelector("#new-player-name");
  const name = cleanPlayerName(input.value);
  if (!name) return;

  const existing = [...lineupState.profiles.keys()].find((player) => player.toLowerCase() === name.toLowerCase());
  if (existing) {
    if (lineupState.selected.size < 12) lineupState.selected.add(existing);
    input.value = "";
    renderPlayerPicker();
    refreshSuggestions();
    return;
  }

  lineupState.profiles.set(name, {
    name,
    played: 0,
    newcomer: true,
    estimate: "unknown",
  });
  if (lineupState.selected.size < 12) lineupState.selected.add(name);
  input.value = "";
  renderPlayerPicker();
  refreshSuggestions();
});

document.querySelector("#clear-selection").addEventListener("click", () => {
  lineupState.selected.clear();
  renderPlayerPicker();
  refreshSuggestions();
});

document.querySelector("#lineup-suggestions").addEventListener("click", (event) => {
  const button = event.target.closest(".copy-lineup");
  if (button) copyLineup(button);
  if (event.target.closest(".more-lineups")) {
    lineupState.visibleSuggestions += 3;
    refreshSuggestions(false);
  }
});

const requestedTab = location.hash.slice(1);
selectTab(tabs.some((tab) => tab.dataset.tab === requestedTab) ? requestedTab : "standings", false);

fetch("matches.txt")
  .then((response) => {
    if (!response.ok) throw new Error("Could not load matches.txt.");
    return response.text();
  })
  .then(parseMatchFile)
  .then(({ matches, upcoming }) => {
    if (!matches.length) throw new Error("No matches found.");
    render(matches, upcoming);
  })
  .catch((error) => {
    console.error(error);
    document.querySelector("#status").textContent =
      "The match file has a formatting error. Please check the latest entry.";
  });
