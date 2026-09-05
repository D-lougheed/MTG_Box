const LC_STORAGE_KEY = "mtgkiosk.lifecounter.v1";
const LC_MIN_PLAYERS = 2;
const LC_MAX_PLAYERS = 8;
const LC_LIFE_CHOICES = [20, 30, 40];
const LC_LETHAL_COMMANDER = 21;
const LC_LETHAL_POISON = 10;
const LC_NAME_MAX = 14;

// Columns per player count, from the Slice 3 layout table. There are always two
// rows: the far row is rotated 180° so opponents read their own total upright.
const LC_COLUMNS = { 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4 };
const LC_LIFE_SIZES = { 1: "132px", 2: "100px", 3: "86px", 4: "64px" };
const LC_NAME_SIZES = { 1: "17px", 2: "14px", 3: "13px", 4: "12px" };

// Walking 40 down to 12 must not cost 28 separate taps, but a single deliberate
// tap still has to move exactly one — hence the delay before repeat starts.
const LC_REPEAT_DELAY = 400;
const LC_REPEAT_FIRST = 300;
const LC_REPEAT_FASTEST = 80;
const LC_REPEAT_DECAY = 0.82;

let lcGame = null;
let lcTiles = [];
let lcBuiltCount = 0;
const lcRepeats = new Map();
let lcDetail = null;
let lcDetailIndex = -1;
let lcResetConfirmTimer = null;
let lcSetupPlayers = 4;
let lcSetupLife = 40;

function lcEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function lcButton(className, text) {
  const el = document.createElement("button");
  el.type = "button";
  el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function lcClamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function lcDefaultName(index) {
  return `Player ${index + 1}`;
}

// Two rows always. The near row fills first so seat 1 sits with whoever set the
// game up; an odd count leaves the far row one short, and its first tile takes
// the spare column rather than leaving a hole in the grid.
function lcSeatPlacement(count) {
  const columns = LC_COLUMNS[count];
  const nearCount = Math.ceil(count / 2);
  const farCount = count - nearCount;
  const seats = [];
  for (let index = 0; index < count; index += 1) {
    const near = index < nearCount;
    const slot = near ? index : index - nearCount;
    const span = !near && slot === 0 ? 1 + columns - farCount : 1;
    const column = near ? slot + 1 : slot === 0 ? 1 : columns - farCount + slot + 1;
    seats.push({ index, near, column, span });
  }
  return { columns, seats };
}

function lcNewGame(count, startingLife) {
  const players = [];
  for (let i = 0; i < count; i += 1) {
    players.push({
      name: lcDefaultName(i),
      life: startingLife,
      poison: 0,
      cmd: new Array(count).fill(0),
    });
  }
  return { startingLife, players };
}

/* Storage. A kiosk reboot mid-game must not lose the game, but a storage
   failure — private mode, quota, a wiped profile — must never take the counter
   down with it, so both directions are defensive and a bad payload falls back
   to a clean state rather than rendering half a game. */

function lcSave() {
  if (!lcGame) return;
  try {
    localStorage.setItem(LC_STORAGE_KEY, JSON.stringify(lcGame));
  } catch (err) {
    console.error("Life counter: couldn't save game", err);
  }
}

function lcSanitise(data) {
  if (!data || typeof data !== "object") return null;
  if (!LC_LIFE_CHOICES.includes(data.startingLife)) return null;
  if (!Array.isArray(data.players)) return null;
  const count = data.players.length;
  if (count < LC_MIN_PLAYERS || count > LC_MAX_PLAYERS) return null;
  const players = [];
  for (let i = 0; i < count; i += 1) {
    const raw = data.players[i];
    if (!raw || typeof raw !== "object") return null;
    if (!Number.isFinite(raw.life) || !Number.isFinite(raw.poison)) return null;
    if (!Array.isArray(raw.cmd) || raw.cmd.length !== count) return null;
    if (!raw.cmd.every((amount) => Number.isFinite(amount))) return null;
    const name = typeof raw.name === "string" ? raw.name.trim().slice(0, LC_NAME_MAX) : "";
    players.push({
      name: name || lcDefaultName(i),
      life: lcClamp(Math.round(raw.life), -99, 999),
      poison: lcClamp(Math.round(raw.poison), 0, 99),
      cmd: raw.cmd.map((amount) => lcClamp(Math.round(amount), 0, 99)),
    });
  }
  return { startingLife: data.startingLife, players };
}

function lcLoad() {
  let stored = null;
  try {
    stored = localStorage.getItem(LC_STORAGE_KEY);
  } catch (err) {
    console.error("Life counter: couldn't read saved game", err);
    return null;
  }
  if (!stored) return null;
  try {
    return lcSanitise(JSON.parse(stored));
  } catch (err) {
    console.error("Life counter: saved game was unreadable", err);
    return null;
  }
}

/* Press-and-hold. A repeat timer that outlives its press would silently drain a
   player's life with nobody touching the screen, so the press captures the
   pointer (the release always comes back to us) and every plausible end-of-press
   signal cancels, including window-level ones the tile itself never sees.

   One repeat per pointer id, not one for the whole table. A single shared slot
   meant a second finger's pointerdown cancelled the first finger's repeat and
   either finger's release cancelled the other's: at eight players, seat 1
   counting down froze the moment seat 2 joined in, still holding, and lost its
   press highlight with it. Two players adjusting at once is the normal case. */

function lcStopRepeat(pointerId) {
  const entry = lcRepeats.get(pointerId);
  if (!entry) return;
  clearTimeout(entry.timer);
  entry.el.classList.remove("lc-pressed");
  lcRepeats.delete(pointerId);
}

function lcStopAllRepeats() {
  lcRepeats.forEach((entry) => {
    clearTimeout(entry.timer);
    entry.el.classList.remove("lc-pressed");
  });
  lcRepeats.clear();
  // A tile torn down mid-press leaves its highlight on an element the map has
  // already forgotten, so the sweep stays as the backstop it always was.
  document.querySelectorAll(".lc-pressed").forEach((el) => el.classList.remove("lc-pressed"));
}

function lcBindRepeat(el, apply) {
  el.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const pointerId = event.pointerId;
    lcStopRepeat(pointerId);
    const target = event.currentTarget;
    target.classList.add("lc-pressed");
    try {
      target.setPointerCapture(pointerId);
    } catch (err) {
      // Capture is best-effort; the window-level listeners below still cancel.
    }
    apply();
    const entry = { el: target, timer: null, interval: LC_REPEAT_FIRST };
    lcRepeats.set(pointerId, entry);
    const tick = () => {
      apply();
      entry.interval = Math.max(LC_REPEAT_FASTEST, Math.round(entry.interval * LC_REPEAT_DECAY));
      entry.timer = setTimeout(tick, entry.interval);
    };
    entry.timer = setTimeout(tick, LC_REPEAT_DELAY);
  });
  ["pointerup", "pointercancel", "pointerleave", "lostpointercapture"].forEach((name) => {
    el.addEventListener(name, (event) => lcStopRepeat(event.pointerId));
  });
}

window.addEventListener("pointerup", (event) => lcStopRepeat(event.pointerId));
window.addEventListener("pointercancel", (event) => lcStopRepeat(event.pointerId));
window.addEventListener("blur", lcStopAllRepeats);
document.addEventListener("visibilitychange", lcStopAllRepeats);

/* Game state changes. */

function lcIsDead(player) {
  if (player.life <= 0) return true;
  if (player.poison >= LC_LETHAL_POISON) return true;
  return player.cmd.some((amount) => amount >= LC_LETHAL_COMMANDER);
}

function lcAdjustLife(index, delta) {
  const player = lcGame.players[index];
  player.life = lcClamp(player.life + delta, -99, 999);
  lcCommit();
}

function lcAdjustCommander(index, opponent, delta) {
  const player = lcGame.players[index];
  player.cmd[opponent] = lcClamp(player.cmd[opponent] + delta, 0, 99);
  lcCommit();
}

function lcAdjustPoison(index, delta) {
  const player = lcGame.players[index];
  player.poison = lcClamp(player.poison + delta, 0, 99);
  lcCommit();
}

function lcResetPlayer(index) {
  const player = lcGame.players[index];
  player.life = lcGame.startingLife;
  player.poison = 0;
  player.cmd = player.cmd.map(() => 0);
  lcCommit();
}

function lcResetGame() {
  lcGame.players.forEach((player) => {
    player.life = lcGame.startingLife;
    player.poison = 0;
    player.cmd = player.cmd.map(() => 0);
  });
  lcCommit();
}

function lcCommit() {
  lcSave();
  lcUpdateTiles();
  lcUpdateDetail();
}

/* Setup screen. */

const lcRoot = document.getElementById("life-counter-root");
const lcSetupScreen = lcEl("div", "lc-screen lc-setup hidden");
const lcGameScreen = lcEl("div", "lc-screen lc-game hidden");
const lcGrid = lcEl("div", "lc-grid");
const lcHubButton = lcButton("lc-hub", "≡");
const lcControlsOverlay = lcEl("div", "lc-overlay lc-controls hidden");
const lcDetailOverlay = lcEl("div", "lc-overlay lc-detail hidden");

const lcCountButtons = [];
const lcLifeButtons = [];

function lcBuildSetup() {
  lcSetupScreen.appendChild(lcEl("h2", null, "Life Counter"));
  const body = lcEl("div", "lc-setup-body");
  const choices = lcEl("div", "lc-setup-choices");

  choices.appendChild(lcEl("p", "lc-label", "Players"));
  const countRow = lcEl("div", "lc-choice-row");
  for (let count = LC_MIN_PLAYERS; count <= LC_MAX_PLAYERS; count += 1) {
    const button = lcButton("lc-choice", String(count));
    button.addEventListener("click", () => {
      lcSetupPlayers = count;
      lcRenderSetup();
    });
    lcCountButtons.push({ button, count });
    countRow.appendChild(button);
  }
  choices.appendChild(countRow);

  choices.appendChild(lcEl("p", "lc-label", "Starting life"));
  const lifeRow = lcEl("div", "lc-choice-row");
  LC_LIFE_CHOICES.forEach((life) => {
    const button = lcButton("lc-choice lc-choice-wide", String(life));
    button.addEventListener("click", () => {
      lcSetupLife = life;
      lcRenderSetup();
    });
    lcLifeButtons.push({ button, life });
    lifeRow.appendChild(button);
  });
  choices.appendChild(lifeRow);

  const startButton = lcButton("lc-button lc-button-primary lc-start", "Start game");
  startButton.addEventListener("click", () => {
    lcGame = lcNewGame(lcSetupPlayers, lcSetupLife);
    lcBuildGrid();
    lcCommit();
    lcShowScreen("game");
  });
  choices.appendChild(startButton);
  body.appendChild(choices);

  const preview = lcEl("div", "lc-setup-preview");
  preview.appendChild(lcEl("p", "lc-label", "Seating"));
  const previewGrid = lcEl("div", "lc-preview-grid");
  preview.appendChild(previewGrid);
  preview.appendChild(lcEl("p", "lc-preview-note", "The far row is upside down so the players opposite read their own total the right way up."));
  body.appendChild(preview);
  lcSetupScreen.appendChild(body);

  const footer = lcEl("div", "lc-setup-footer");
  const backButton = lcButton("back-button", "Back");
  backButton.addEventListener("click", () => showView("menu"));
  footer.appendChild(backButton);

  const resumeButton = lcButton("lc-button lc-button-ghost hidden", "Back to game");
  resumeButton.addEventListener("click", () => {
    if (lcGame) lcShowScreen("game");
  });
  footer.appendChild(resumeButton);
  lcSetupScreen.appendChild(footer);

  return { resumeButton, previewGrid };
}

const lcSetupRefs = lcBuildSetup();

function lcRenderSetup() {
  lcCountButtons.forEach((entry) => {
    entry.button.classList.toggle("lc-chosen", entry.count === lcSetupPlayers);
  });
  lcLifeButtons.forEach((entry) => {
    entry.button.classList.toggle("lc-chosen", entry.life === lcSetupLife);
  });
  lcSetupRefs.resumeButton.classList.toggle("hidden", !lcGame);

  // A scale model of the table, rotated seats and all: it is the fastest way to
  // explain what the 180° far row is going to do before the game starts.
  const grid = lcSetupRefs.previewGrid;
  const { columns, seats } = lcSeatPlacement(lcSetupPlayers);
  grid.innerHTML = "";
  grid.style.setProperty("--lc-cols", String(columns));
  seats.forEach((seat) => {
    const cell = lcEl("div", "lc-preview-cell", String(seat.index + 1));
    if (!seat.near) cell.classList.add("lc-rotated");
    cell.style.setProperty("--lc-seat", `var(--lc-seat-${seat.index + 1})`);
    cell.style.gridRow = seat.near ? "2" : "1";
    cell.style.gridColumn = `${seat.column} / span ${seat.span}`;
    grid.appendChild(cell);
  });
}

/* Game grid. Tiles are built once per game and only their text is rewritten
   afterwards: rebuilding mid-press would tear the captured element out from
   under an active auto-repeat and strand its timer. */

function lcBuildGrid() {
  lcStopAllRepeats();
  lcGrid.innerHTML = "";
  lcTiles = [];
  const count = lcGame.players.length;
  const { columns, seats } = lcSeatPlacement(count);
  lcBuiltCount = count;
  lcGameScreen.style.setProperty("--lc-cols", String(columns));
  lcGameScreen.style.setProperty("--lc-life-size", LC_LIFE_SIZES[columns]);
  lcGameScreen.style.setProperty("--lc-name-size", LC_NAME_SIZES[columns]);
  seats.forEach((seat) => lcGrid.appendChild(lcBuildTile(seat)));
}

function lcBuildTile(seat) {
  const index = seat.index;
  const tile = lcEl("div", "lc-tile");
  if (!seat.near) tile.classList.add("lc-rotated");
  tile.style.setProperty("--lc-seat", `var(--lc-seat-${index + 1})`);
  tile.style.gridRow = seat.near ? "2" : "1";
  tile.style.gridColumn = `${seat.column} / span ${seat.span}`;

  const minus = lcButton("lc-zone lc-zone-minus", "−");
  const plus = lcButton("lc-zone lc-zone-plus", "+");
  lcBindRepeat(minus, () => lcAdjustLife(index, -1));
  lcBindRepeat(plus, () => lcAdjustLife(index, 1));
  tile.appendChild(minus);
  tile.appendChild(plus);

  const face = lcEl("div", "lc-tile-face");
  const name = lcEl("div", "lc-name");
  const life = lcButton("lc-life");
  life.addEventListener("click", () => lcOpenDetail(index));
  const badges = lcEl("div", "lc-badges");
  const poisonBadge = lcEl("span", "lc-badge lc-badge-poison hidden");
  const commanderBadge = lcEl("span", "lc-badge lc-badge-commander hidden");
  const deadBadge = lcEl("span", "lc-badge lc-badge-dead hidden", "dead");
  badges.appendChild(deadBadge);
  badges.appendChild(poisonBadge);
  badges.appendChild(commanderBadge);
  face.appendChild(name);
  face.appendChild(life);
  face.appendChild(badges);
  tile.appendChild(face);

  lcTiles.push({ tile, name, life, poisonBadge, commanderBadge, deadBadge });
  return tile;
}

function lcUpdateTiles() {
  if (!lcGame) return;
  lcGame.players.forEach((player, index) => {
    const refs = lcTiles[index];
    if (!refs) return;
    const text = String(player.life);
    refs.name.textContent = player.name;
    refs.life.textContent = text;
    // Three digits at the full size would eat into the ±1 zones either side.
    refs.life.classList.toggle("lc-life-wide", text.length >= 3);

    const worstCommander = Math.max(0, ...player.cmd);
    const poisonLethal = player.poison >= LC_LETHAL_POISON;
    const commanderLethal = worstCommander >= LC_LETHAL_COMMANDER;
    refs.poisonBadge.textContent = `poison ${player.poison}`;
    refs.poisonBadge.classList.toggle("lc-badge-lethal", poisonLethal);
    refs.commanderBadge.textContent = `cmdr ${worstCommander}`;
    refs.commanderBadge.classList.toggle("lc-badge-lethal", commanderLethal);

    const dead = lcIsDead(player);
    refs.tile.classList.toggle("lc-dead", dead);

    // Three badges overrun a 190px tile at eight players, so the row is capped
    // at two and lethal counters outrank merely present ones for the slot.
    const shown = [];
    if (dead) shown.push(refs.deadBadge);
    if (poisonLethal) shown.push(refs.poisonBadge);
    if (commanderLethal) shown.push(refs.commanderBadge);
    if (player.poison > 0 && !poisonLethal) shown.push(refs.poisonBadge);
    if (worstCommander > 0 && !commanderLethal) shown.push(refs.commanderBadge);
    const visible = shown.slice(0, 2);
    [refs.deadBadge, refs.poisonBadge, refs.commanderBadge].forEach((badge) => {
      badge.classList.toggle("hidden", !visible.includes(badge));
    });
  });
}

/* Detail panel. Rebuilt on open — at most seven opponents, and nothing here
   survives a close, so there is no stale state to reconcile. */

function lcCreateStepper(label, seatIndex) {
  const row = lcEl("div", "lc-stepper");
  const name = lcEl("span", "lc-stepper-label", label);
  if (seatIndex !== null) name.style.setProperty("--lc-seat", `var(--lc-seat-${seatIndex + 1})`);
  const minus = lcButton("lc-step", "−");
  const value = lcEl("span", "lc-stepper-value", "0");
  const plus = lcButton("lc-step", "+");
  row.appendChild(name);
  row.appendChild(minus);
  row.appendChild(value);
  row.appendChild(plus);
  return { row, minus, value, plus };
}

function lcBuildDetail(index) {
  const player = lcGame.players[index];
  lcDetailOverlay.innerHTML = "";
  const card = lcEl("div", "lc-detail-card");
  card.style.setProperty("--lc-seat", `var(--lc-seat-${index + 1})`);

  const head = lcEl("div", "lc-detail-head");
  const nameButton = lcButton("lc-detail-name", player.name);
  const lifeValue = lcEl("span", "lc-detail-life", String(player.life));
  const closeButton = lcButton("lc-detail-close", "×");
  head.appendChild(nameButton);
  head.appendChild(lifeValue);
  head.appendChild(closeButton);
  card.appendChild(head);

  // The on-screen keyboard covers the bottom half of the screen, so editing a
  // name swaps the panel for a single row rather than hiding controls under it.
  const editor = lcEl("div", "lc-name-editor hidden");
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.className = "lc-name-input";
  nameInput.maxLength = LC_NAME_MAX;
  const doneButton = lcButton("lc-button lc-button-primary", "Done");
  const editorRow = lcEl("div", "lc-name-editor-row");
  editorRow.appendChild(nameInput);
  editorRow.appendChild(doneButton);
  editor.appendChild(lcEl("p", "lc-label", "Player name"));
  editor.appendChild(editorRow);
  card.appendChild(editor);

  const body = lcEl("div", "lc-detail-body");
  body.appendChild(lcEl("p", "lc-label", "Commander damage received"));
  const commanderGrid = lcEl("div", "lc-cmd-grid");
  const opponents = [];
  lcGame.players.forEach((opponent, opponentIndex) => {
    if (opponentIndex === index) return;
    const stepper = lcCreateStepper(opponent.name, opponentIndex);
    lcBindRepeat(stepper.minus, () => lcAdjustCommander(index, opponentIndex, -1));
    lcBindRepeat(stepper.plus, () => lcAdjustCommander(index, opponentIndex, 1));
    opponents.push({ opponentIndex, stepper });
    commanderGrid.appendChild(stepper.row);
  });
  // Seven opponents in two columns needs four rows, which pushes poison below
  // the fold on a 480px screen; three columns keeps the whole panel visible.
  commanderGrid.classList.toggle("lc-cmd-grid-single", opponents.length === 1);
  commanderGrid.classList.toggle("lc-cmd-grid-wide", opponents.length >= 5);
  body.appendChild(commanderGrid);

  body.appendChild(lcEl("p", "lc-label", "Poison counters"));
  const poison = lcCreateStepper("Poison", null);
  poison.row.classList.add("lc-stepper-poison");
  lcBindRepeat(poison.minus, () => lcAdjustPoison(index, -1));
  lcBindRepeat(poison.plus, () => lcAdjustPoison(index, 1));
  body.appendChild(poison.row);
  card.appendChild(body);

  const actions = lcEl("div", "lc-detail-actions");
  const resetButton = lcButton("lc-button lc-button-danger", "Reset this player");
  resetButton.addEventListener("click", () => lcResetPlayer(index));
  const closeAction = lcButton("lc-button lc-button-primary", "Close");
  closeAction.addEventListener("click", lcCloseDetail);
  actions.appendChild(resetButton);
  actions.appendChild(closeAction);
  card.appendChild(actions);

  lcDetailOverlay.appendChild(card);

  const openEditor = () => {
    nameInput.value = player.name;
    card.classList.add("lc-editing");
    editor.classList.remove("hidden");
    showKeyboardFor(nameInput);
  };
  const commitEditor = () => {
    const trimmed = nameInput.value.trim().slice(0, LC_NAME_MAX);
    player.name = trimmed || lcDefaultName(index);
    card.classList.remove("lc-editing");
    editor.classList.add("hidden");
    hideKeyboard();
    lcCommit();
  };
  nameButton.addEventListener("click", openEditor);
  doneButton.addEventListener("click", commitEditor);
  closeButton.addEventListener("click", lcCloseDetail);

  return { card, nameButton, lifeValue, opponents, poison };
}

function lcOpenDetail(index) {
  lcStopAllRepeats();
  lcDetailIndex = index;
  lcDetail = lcBuildDetail(index);
  lcDetailOverlay.classList.remove("hidden");
  lcUpdateDetail();
}

function lcCloseDetail() {
  if (lcDetail) lcDetail.card.classList.remove("lc-editing");
  hideKeyboard();
  lcStopAllRepeats();
  lcDetailOverlay.classList.add("hidden");
  lcDetailOverlay.innerHTML = "";
  lcDetail = null;
  lcDetailIndex = -1;
}

function lcUpdateDetail() {
  if (!lcDetail || lcDetailIndex < 0) return;
  const player = lcGame.players[lcDetailIndex];
  lcDetail.nameButton.textContent = player.name;
  lcDetail.lifeValue.textContent = String(player.life);
  lcDetail.lifeValue.classList.toggle("lc-detail-life-dead", player.life <= 0);
  lcDetail.opponents.forEach((entry) => {
    const amount = player.cmd[entry.opponentIndex];
    entry.stepper.value.textContent = String(amount);
    entry.stepper.row.classList.toggle("lc-lethal", amount >= LC_LETHAL_COMMANDER);
  });
  lcDetail.poison.value.textContent = String(player.poison);
  lcDetail.poison.row.classList.toggle("lc-lethal", player.poison >= LC_LETHAL_POISON);
}

/* Game controls, reached from the hub button at the centre of the table. */

function lcBuildControls() {
  const card = lcEl("div", "lc-card");
  card.appendChild(lcEl("h2", null, "Game"));

  const resetButton = lcButton("lc-button lc-button-ghost", "Reset game");
  // Two-step: a misfired reset wipes a game in progress, and there is no undo.
  resetButton.addEventListener("click", () => {
    if (lcResetConfirmTimer !== null) {
      lcClearResetConfirm(resetButton);
      lcResetGame();
      lcCloseControls();
      return;
    }
    resetButton.textContent = "Tap again to confirm";
    resetButton.classList.add("lc-confirming");
    lcResetConfirmTimer = setTimeout(() => lcClearResetConfirm(resetButton), 3000);
  });
  card.appendChild(resetButton);

  const newButton = lcButton("lc-button lc-button-ghost", "New game");
  newButton.addEventListener("click", () => {
    lcCloseControls();
    lcRenderSetup();
    lcShowScreen("setup");
  });
  card.appendChild(newButton);

  const menuButton = lcButton("lc-button lc-button-ghost", "Main menu");
  menuButton.addEventListener("click", () => {
    lcCloseControls();
    showView("menu");
  });
  card.appendChild(menuButton);

  const closeButton = lcButton("lc-button lc-button-primary", "Resume");
  closeButton.addEventListener("click", lcCloseControls);
  card.appendChild(closeButton);

  lcControlsOverlay.appendChild(card);
  lcControlsOverlay.addEventListener("click", (event) => {
    if (event.target === lcControlsOverlay) lcCloseControls();
  });
  return resetButton;
}

function lcClearResetConfirm(button) {
  if (lcResetConfirmTimer !== null) {
    clearTimeout(lcResetConfirmTimer);
    lcResetConfirmTimer = null;
  }
  button.textContent = "Reset game";
  button.classList.remove("lc-confirming");
}

const lcResetButton = lcBuildControls();

function lcCloseControls() {
  lcClearResetConfirm(lcResetButton);
  lcControlsOverlay.classList.add("hidden");
}

lcHubButton.addEventListener("click", () => {
  lcStopAllRepeats();
  lcControlsOverlay.classList.remove("hidden");
});

/* Screens and bootstrap. */

function lcShowScreen(name) {
  lcSetupScreen.classList.toggle("hidden", name !== "setup");
  lcGameScreen.classList.toggle("hidden", name !== "game");
}

// A press that ends after the view is gone never delivers a pointerup here, and
// its repeat would keep adjusting a life total nobody can see.
function onLifeCounterHidden() {
  lcStopAllRepeats();
}

function onLifeCounterShown() {
  lcStopAllRepeats();
  lcCloseDetail();
  lcCloseControls();
  if (!lcGame) lcGame = lcLoad();
  if (lcGame) {
    if (lcBuiltCount !== lcGame.players.length) lcBuildGrid();
    lcUpdateTiles();
    lcShowScreen("game");
  } else {
    lcRenderSetup();
    lcShowScreen("setup");
  }
}

lcGameScreen.appendChild(lcGrid);
lcGameScreen.appendChild(lcHubButton);
lcRoot.appendChild(lcSetupScreen);
lcRoot.appendChild(lcGameScreen);
lcRoot.appendChild(lcControlsOverlay);
lcRoot.appendChild(lcDetailOverlay);

lcGame = lcLoad();
if (lcGame) {
  lcSetupPlayers = lcGame.players.length;
  lcSetupLife = lcGame.startingLife;
  lcBuildGrid();
  lcUpdateTiles();
  lcShowScreen("game");
} else {
  lcRenderSetup();
  lcShowScreen("setup");
}
