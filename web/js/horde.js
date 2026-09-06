// Horde Mode.
//
// The whole game loop lives in the browser on purpose: the server holds no
// session, so a backend restart cannot lose a game in progress. The server is
// only asked for a list of playable creature types and a generated deck.
//
// This follows the divergence from paper Horde Magic settled in the design
// spec: the Oracle export has no token cards, so the horde deck is real
// creature cards of one subtype and reveals a fixed number per turn rather
// than "until a non-token is revealed", which has no stopping condition here.

const HORDE_STORAGE_KEY = "mtgkiosk.horde";
const HORDE_STATE_VERSION = 1;

// Sizes and reveal rates are the server's to decide - these labels only
// describe what the player is choosing. The deck response carries the
// authoritative cards_per_turn.
const HORDE_DIFFICULTIES = [
  { value: "easy", label: "Easy", detail: "40 cards · 1/turn", perTurn: 1 },
  { value: "normal", label: "Normal", detail: "60 cards · 2/turn", perTurn: 2 },
  { value: "hard", label: "Hard", detail: "80 cards · 3/turn", perTurn: 3 },
];
const HORDE_PLAYER_COUNTS = [1, 2, 3, 4];
const HORDE_STARTING_LIVES = [20, 30, 40];

// Tokens are entered with steppers rather than typed, so the ranges only have
// to cover what a real token-making card produces. 99 clears anything Magic
// prints; 20 at once clears the widest army-in-a-can effects.
const HORDE_TOKEN_MAX_PT = 99;
const HORDE_TOKEN_MAX_COUNT = 20;

const hordeUi = {};
const hordeSetupChoice = { subtype: null, difficulty: "normal", players: 2, life: 20 };

let hordeGame = null;
let hordeSubtypesState = "idle";
let hordeUndo = null;
let hordeStarting = false;

// The open creature panel: { creature, mode, detail }. Held as an object so an
// in-flight detail fetch can check it is still looking at the same panel, not
// just the same token.
let hordeCardPanel = null;

// Bumped by every open, close and mode change. A detail fetch or an image load
// that resolves after its bump has been left behind and must not paint.
let hordeDetailToken = 0;

// Card detail is fetched on demand rather than persisted, so the same creature
// gets looked up repeatedly across a game. Bounded by the deck (80 cards at
// most) and dropped when the game ends.
const hordeDetailCache = new Map();

// Remembered between opens: a Zombie horde makes 2/2 Zombies all game, and
// re-entering the same four values every time is the chore this screen exists
// to remove. Reset with the game, since the subtype changes with it.
let hordeTokenDraft = null;

function hordeEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

// Inline SVG rather than an emoji. The Pi ships no colour-emoji font, so a
// character above the BMP renders as an empty box on the real device - the
// same reason index.html draws the dice button rather than using U+1F3B2.
// The markup is a constant in this file and never carries card or user data.
function hordeIcon(className, markup) {
  const node = hordeEl("span", className);
  node.innerHTML = markup;
  return node;
}

const HORDE_ICON_CARD_BOX =
  '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
  '<rect x="3" y="7" width="18" height="13" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/>' +
  '<path d="M7 7V5.5A2.5 2.5 0 0 1 9.5 3h5A2.5 2.5 0 0 1 17 5.5V7" fill="none" stroke="currentColor" stroke-width="1.8"/>' +
  '<path d="M8.5 11.5h7M8.5 15.5h7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' +
  "</svg>";

function hordeButton(className, text, onClick) {
  const node = hordeEl("button", className, text);
  node.type = "button";
  if (onClick) node.addEventListener("click", onClick);
  return node;
}

function hordeCapitalise(text) {
  const value = String(text || "");
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}

// Power is text, not a number: "*" and "1+*" are legal Magic values. Anything
// without a fixed value counts as 0 towards the total rather than producing
// NaN, and the battlefield shows the real string so nobody is misled.
function hordePowerValue(creature) {
  const raw = creature ? creature.power : null;
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : 0;
  if (typeof raw !== "string") return 0;
  const trimmed = raw.trim();
  if (!/^-?\d+$/.test(trimmed)) return 0;
  return parseInt(trimmed, 10);
}

function hordeHasVariablePower(creature) {
  const raw = creature ? creature.power : null;
  return typeof raw === "string" && !/^-?\d+$/.test(raw.trim());
}

function hordeFormatPT(creature) {
  const power = creature.power === null || creature.power === undefined || creature.power === "" ? "–" : String(creature.power);
  const toughness = creature.toughness === null || creature.toughness === undefined || creature.toughness === "" ? "–" : String(creature.toughness);
  return power + "/" + toughness;
}

function hordeTotalPower() {
  return hordeGame.battlefield.reduce((total, creature) => total + hordePowerValue(creature), 0);
}

/* ---------- persistence ---------- */

function hordeCardText(value) {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

// Only the four fields the game ever displays are kept. The full card objects
// carry oracle text and image URLs that nothing here reads, and a slim deck
// keeps the localStorage write on every single life tap cheap.
function hordeSlimCard(card) {
  return {
    id: typeof card.id === "string" ? card.id : "",
    name: typeof card.name === "string" ? card.name : "Unknown creature",
    power: hordeCardText(card.power),
    toughness: hordeCardText(card.toughness),
  };
}

// Player-made tokens share the battlefield with revealed cards, so they carry
// the same four fields and count towards Horde power through exactly the same
// code. `tok` is the only thing that separates them, and it is deliberately
// optional: a game saved before tokens existed has no such field, and must
// still load rather than being thrown away as a stale shape. That is also why
// HORDE_STATE_VERSION is unchanged - bumping it would reject those saves.
function hordeIsToken(creature) {
  return !!creature && creature.tok === true;
}

function hordeMakeToken(name, power, toughness) {
  return {
    id: "",
    name: name,
    power: String(power),
    toughness: String(toughness),
    tok: true,
  };
}

function isValidHordeCard(card) {
  return !!card && typeof card === "object" && typeof card.name === "string" && card.name.length > 0;
}

function isValidHordeGame(data) {
  if (!data || typeof data !== "object") return false;
  if (data.v !== HORDE_STATE_VERSION) return false;
  if (typeof data.subtype !== "string" || typeof data.difficulty !== "string") return false;
  if (!Number.isFinite(data.cardsPerTurn) || data.cardsPerTurn < 1) return false;
  if (!Number.isFinite(data.turn) || data.turn < 0) return false;
  if (!Array.isArray(data.library) || !data.library.every(isValidHordeCard)) return false;
  if (!Array.isArray(data.battlefield) || !data.battlefield.every(isValidHordeCard)) return false;
  if (!Array.isArray(data.players) || data.players.length < 1 || data.players.length > 4) return false;
  if (!data.players.every((player) => player && typeof player.name === "string" && Number.isFinite(player.life))) return false;
  if (data.over !== null && data.over !== "players" && data.over !== "horde") return false;
  return true;
}

function saveHordeGame() {
  try {
    if (hordeGame) {
      localStorage.setItem(HORDE_STORAGE_KEY, JSON.stringify(hordeGame));
    } else {
      localStorage.removeItem(HORDE_STORAGE_KEY);
    }
  } catch (err) {
    // Storage can be full, disabled, or blocked by the browser. The game stays
    // playable in memory; it just won't survive a reboot.
  }
}

function clearStoredHordeGame() {
  try {
    localStorage.removeItem(HORDE_STORAGE_KEY);
  } catch (err) {
    // Nothing useful to do - the entry is already being ignored.
  }
}

function restoreHordeGame() {
  let raw = null;
  try {
    raw = localStorage.getItem(HORDE_STORAGE_KEY);
  } catch (err) {
    return;
  }
  if (!raw) return;
  let data = null;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    clearStoredHordeGame();
    return;
  }
  // A corrupt or older-shaped entry must drop the player back on a clean setup
  // screen rather than half-restoring a game that then crashes the view.
  if (!isValidHordeGame(data)) {
    clearStoredHordeGame();
    return;
  }
  // "Just revealed" is about the last tap, not the last boot. `tok` is dropped
  // rather than validated when it isn't exactly true, so that both a pre-token
  // save (field absent) and a hand-mangled one (field present but junk) land on
  // a clean shape instead of costing the player their game. Dropped rather than
  // set to false so a revealed card never carries the key at all - it would
  // otherwise cost bytes on every one of the 80 entries, on a write that
  // happens on every single life tap.
  data.battlefield.forEach((creature) => {
    creature.neu = false;
    if (creature.tok !== true) delete creature.tok;
  });
  hordeGame = data;
}

/* ---------- setup screen ---------- */

function buildHordeOptionGroup(label, modifier, choices, current, onPick) {
  const group = hordeEl("div", "horde-option-group horde-option-group--" + modifier);
  group.appendChild(hordeEl("div", "horde-label", label));
  const row = hordeEl("div", "horde-option-row");
  const buttons = [];
  choices.forEach((choice) => {
    const option = hordeButton("horde-option", null, () => {
      buttons.forEach((other) => other.classList.toggle("horde-option--on", other === option));
      onPick(choice.value);
    });
    option.appendChild(hordeEl("span", "horde-option-label", choice.label));
    if (choice.detail) option.appendChild(hordeEl("span", "horde-option-detail", choice.detail));
    if (choice.value === current) option.classList.add("horde-option--on");
    buttons.push(option);
    row.appendChild(option);
  });
  group.appendChild(row);
  return group;
}

function buildHordeNoDatabase() {
  const box = hordeEl("div", "horde-nodb");
  box.appendChild(hordeIcon("horde-nodb-icon", HORDE_ICON_CARD_BOX));
  box.appendChild(hordeEl("h3", "horde-nodb-title", "No card database yet"));
  box.appendChild(hordeEl("p", "horde-nodb-text",
    "Horde Mode builds its deck from cards stored on this device. Download the card database from Settings, then come back."));
  hordeUi.noDatabaseDetail = hordeEl("p", "horde-nodb-detail", "");
  box.appendChild(hordeUi.noDatabaseDetail);
  const actions = hordeEl("div", "horde-nodb-actions");
  actions.appendChild(hordeButton("horde-primary", "Open Settings", () => showView("settings")));
  actions.appendChild(hordeButton("horde-secondary", "Try again", loadHordeSubtypes));
  box.appendChild(actions);
  return box;
}

function buildHordeSetupScreen() {
  const screen = hordeEl("div", "horde-screen horde-setup");

  const head = hordeEl("div", "horde-setup-head");
  head.appendChild(hordeEl("h2", "horde-setup-title", "Horde Mode"));
  head.appendChild(hordeEl("p", "horde-setup-sub",
    "The horde attacks every turn and never blocks. Survive until its library and battlefield are empty."));
  screen.appendChild(head);

  const body = hordeEl("div", "horde-setup-body");
  body.appendChild(hordeEl("div", "horde-label", "Creature type"));
  hordeUi.subtypeStatus = hordeEl("p", "horde-status", "Loading creature types…");
  body.appendChild(hordeUi.subtypeStatus);
  hordeUi.subtypeList = hordeEl("div", "horde-subtype-list");
  body.appendChild(hordeUi.subtypeList);

  const options = hordeEl("div", "horde-options");
  options.appendChild(buildHordeOptionGroup(
    "Difficulty", "difficulty",
    HORDE_DIFFICULTIES,
    hordeSetupChoice.difficulty,
    (value) => { hordeSetupChoice.difficulty = value; }));
  options.appendChild(buildHordeOptionGroup(
    "Players", "players",
    HORDE_PLAYER_COUNTS.map((count) => ({ value: count, label: String(count) })),
    hordeSetupChoice.players,
    (value) => { hordeSetupChoice.players = value; }));
  options.appendChild(buildHordeOptionGroup(
    "Starting life", "life",
    HORDE_STARTING_LIVES.map((life) => ({ value: life, label: String(life) })),
    hordeSetupChoice.life,
    (value) => { hordeSetupChoice.life = value; }));
  body.appendChild(options);
  screen.appendChild(body);
  hordeUi.setupBody = body;

  hordeUi.noDatabase = buildHordeNoDatabase();
  hordeUi.noDatabase.classList.add("hidden");
  screen.appendChild(hordeUi.noDatabase);

  const footer = hordeEl("div", "horde-footer");
  footer.appendChild(hordeButton("back-button horde-back", "Back", () => showView("menu")));
  hordeUi.setupError = hordeEl("p", "horde-footer-message", "");
  footer.appendChild(hordeUi.setupError);
  hordeUi.startButton = hordeButton("horde-primary", "Start game", startHordeGame);
  footer.appendChild(hordeUi.startButton);
  screen.appendChild(footer);

  return screen;
}

function setHordeSetupMode(mode) {
  const missing = mode === "nodb";
  hordeUi.setupBody.classList.toggle("hidden", missing);
  hordeUi.noDatabase.classList.toggle("hidden", !missing);
  hordeUi.startButton.classList.toggle("hidden", missing);
}

function selectHordeSubtype(name) {
  hordeSetupChoice.subtype = name;
  hordeUi.subtypeList.querySelectorAll(".horde-chip").forEach((chip) => {
    chip.classList.toggle("horde-chip--on", chip.dataset.subtype === name);
  });
  hordeUi.startButton.disabled = !name;
}

function renderHordeSubtypes(list) {
  hordeUi.subtypeList.innerHTML = "";
  const names = [];
  list.forEach((entry) => {
    const name = Array.isArray(entry) ? entry[0] : entry;
    const count = Array.isArray(entry) ? entry[1] : null;
    if (typeof name !== "string" || !name) return;
    names.push(name);
    const chip = hordeButton("horde-chip", null, () => selectHordeSubtype(name));
    chip.dataset.subtype = name;
    chip.appendChild(hordeEl("span", "horde-chip-name", name));
    chip.appendChild(hordeEl("span", "horde-chip-count", Number.isFinite(count) ? count + " cards" : ""));
    hordeUi.subtypeList.appendChild(chip);
  });
  if (names.length === 0) {
    setHordeSetupMode("nodb");
    return;
  }
  hordeUi.subtypeStatus.classList.add("hidden");
  // The list is most-common-first, so the top entry is always a playable
  // default - leaving nothing selected would make Start a dead button.
  const chosen = names.indexOf(hordeSetupChoice.subtype) !== -1 ? hordeSetupChoice.subtype : names[0];
  selectHordeSubtype(chosen);
  const selected = hordeUi.subtypeList.querySelector(".horde-chip--on");
  if (selected) selected.scrollIntoView({ block: "nearest" });
}

async function loadHordeSubtypes() {
  if (hordeSubtypesState === "loading") return;
  hordeSubtypesState = "loading";
  hordeUi.setupError.textContent = "";
  hordeUi.noDatabaseDetail.textContent = "";
  setHordeSetupMode("list");
  hordeUi.subtypeList.innerHTML = "";
  hordeUi.subtypeStatus.textContent = "Loading creature types…";
  hordeUi.subtypeStatus.classList.remove("hidden");
  try {
    const response = await fetch("/api/horde/subtypes");
    if (!response.ok) {
      hordeSubtypesState = "error";
      setHordeSetupMode("nodb");
      hordeUi.noDatabaseDetail.textContent = "The device answered with HTTP " + response.status + ".";
      return;
    }
    const data = await response.json();
    const list = data && Array.isArray(data.subtypes) ? data.subtypes : [];
    if (list.length === 0) {
      hordeSubtypesState = "error";
      setHordeSetupMode("nodb");
      return;
    }
    hordeSubtypesState = "ready";
    renderHordeSubtypes(list);
  } catch (err) {
    hordeSubtypesState = "error";
    setHordeSetupMode("nodb");
    hordeUi.noDatabaseDetail.textContent = firstLine(err.message);
  }
}

function hordeDefaultPerTurn(difficulty) {
  const match = HORDE_DIFFICULTIES.filter((entry) => entry.value === difficulty)[0];
  return match ? match.perTurn : 2;
}

async function startHordeGame() {
  if (hordeStarting || !hordeSetupChoice.subtype) return;
  hordeStarting = true;
  hordeUi.startButton.disabled = true;
  hordeUi.startButton.textContent = "Building deck…";
  hordeUi.setupError.textContent = "";
  try {
    const response = await fetch("/api/horde/deck", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subtype: hordeSetupChoice.subtype, difficulty: hordeSetupChoice.difficulty }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      hordeUi.setupError.textContent = "Couldn't build a deck: " + firstLine(data.detail || String(response.status));
      return;
    }
    const data = await response.json();
    const cards = (data && Array.isArray(data.cards) ? data.cards : []).filter(isValidHordeCard).map(hordeSlimCard);
    if (cards.length === 0) {
      hordeUi.setupError.textContent = "That deck came back empty. Try another creature type.";
      return;
    }
    const perTurn = Number.isFinite(data.cards_per_turn) && data.cards_per_turn >= 1
      ? Math.floor(data.cards_per_turn)
      : hordeDefaultPerTurn(hordeSetupChoice.difficulty);
    hordeGame = {
      v: HORDE_STATE_VERSION,
      subtype: typeof data.subtype === "string" ? data.subtype : hordeSetupChoice.subtype,
      difficulty: typeof data.difficulty === "string" ? data.difficulty : hordeSetupChoice.difficulty,
      cardsPerTurn: perTurn,
      library: cards,
      battlefield: [],
      players: HORDE_PLAYER_COUNTS.slice(0, hordeSetupChoice.players).map((n) => ({
        name: "P" + n,
        life: hordeSetupChoice.life,
      })),
      turn: 0,
      over: null,
    };
    saveHordeGame();
    enterHordeGame();
  } catch (err) {
    hordeUi.setupError.textContent = "Couldn't build a deck: " + firstLine(err.message);
  } finally {
    hordeStarting = false;
    hordeUi.startButton.disabled = !hordeSetupChoice.subtype;
    hordeUi.startButton.textContent = "Start game";
  }
}

/* ---------- game screen ---------- */

function buildHordeStat(label) {
  const box = hordeEl("div", "horde-stat");
  box.appendChild(hordeEl("div", "horde-stat-label", label));
  const value = hordeEl("div", "horde-stat-value", "0");
  box.appendChild(value);
  return { el: box, value: value };
}

function buildHordeGameScreen() {
  const screen = hordeEl("div", "horde-screen horde-game");

  const header = hordeEl("div", "horde-header");
  header.appendChild(hordeButton("back-button horde-back", "Menu", () => showView("menu")));
  const title = hordeEl("div", "horde-header-title");
  hordeUi.gameTitle = hordeEl("div", "horde-header-name", "");
  hordeUi.gameMeta = hordeEl("div", "horde-header-meta", "");
  title.appendChild(hordeUi.gameTitle);
  title.appendChild(hordeUi.gameMeta);
  header.appendChild(title);
  hordeUi.libraryStat = buildHordeStat("Library");
  hordeUi.powerStat = buildHordeStat("Horde power");
  header.appendChild(hordeUi.libraryStat.el);
  header.appendChild(hordeUi.powerStat.el);
  header.appendChild(hordeButton("horde-abandon", "End game", confirmAbandonHorde));
  screen.appendChild(header);

  const body = hordeEl("div", "horde-body");

  const field = hordeEl("div", "horde-field");
  const fieldHead = hordeEl("div", "horde-field-head");
  hordeUi.fieldTitle = hordeEl("span", "horde-field-title", "Battlefield");
  fieldHead.appendChild(hordeUi.fieldTitle);
  hordeUi.undoButton = hordeButton("horde-undo hidden", "Undo", undoHordeRemoval);
  fieldHead.appendChild(hordeUi.undoButton);
  // Tokens live on the battlefield, so their control lives on the battlefield's
  // own header rather than beside the life totals.
  fieldHead.appendChild(hordeButton("horde-tokens-button", "+ Tokens", openHordeTokenDialog));
  field.appendChild(fieldHead);
  hordeUi.fieldScroll = hordeEl("div", "horde-field-scroll");
  hordeUi.fieldGrid = hordeEl("div", "horde-field-grid");
  hordeUi.fieldEmpty = hordeEl("p", "horde-field-empty", "Nothing on the battlefield. Tap Horde turn to wake it up.");
  hordeUi.fieldScroll.appendChild(hordeUi.fieldGrid);
  hordeUi.fieldScroll.appendChild(hordeUi.fieldEmpty);
  field.appendChild(hordeUi.fieldScroll);
  body.appendChild(field);

  const side = hordeEl("div", "horde-side");
  hordeUi.playersEl = hordeEl("div", "horde-players");
  side.appendChild(hordeUi.playersEl);
  hordeUi.turnButton = hordeButton("horde-turn-button", null, takeHordeTurn);
  hordeUi.turnLabel = hordeEl("span", "horde-turn-label", "Horde turn");
  hordeUi.turnDetail = hordeEl("span", "horde-turn-detail", "");
  hordeUi.turnButton.appendChild(hordeUi.turnLabel);
  hordeUi.turnButton.appendChild(hordeUi.turnDetail);
  side.appendChild(hordeUi.turnButton);
  body.appendChild(side);

  screen.appendChild(body);
  return screen;
}

// Held down rather than tapped, because horde damage arrives in double figures
// every turn and tapping -1 nineteen times is exactly the arithmetic chore this
// screen exists to remove.
//
// Keyed by pointer id, because a repeat is per finger. Two players adjusting at
// once is normal at a four-player table, and while every stepper shared one
// window-level stop, either finger's release cancelled both repeats: lifting one
// froze the other while it was still held down.
const hordeRepeats = new Map();

// A repeat that outlives its press is worse than a frozen one. adjustHordeLife
// re-reads the module-level hordeGame every tick, so an orphan follows whatever
// game is current: holding -1 and tapping Menu with a second finger drained 40
// life while the kiosk sat on the main menu, and abandoning mid-hold carried the
// drain straight into the next game's totals.
function stopHordeRepeat(pointerId) {
  const entry = hordeRepeats.get(pointerId);
  if (!entry) return;
  clearTimeout(entry.timer);
  hordeRepeats.delete(pointerId);
}

function stopAllHordeRepeats() {
  hordeRepeats.forEach((entry) => clearTimeout(entry.timer));
  hordeRepeats.clear();
}

function attachHordeStepper(buttonEl, index, delta) {
  buttonEl.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const pointerId = event.pointerId;
    stopHordeRepeat(pointerId);
    const entry = { timer: null, repeats: 0 };
    hordeRepeats.set(pointerId, entry);
    adjustHordeLife(index, delta);
    const repeat = () => {
      entry.repeats += 1;
      adjustHordeLife(index, delta);
      entry.timer = setTimeout(repeat, entry.repeats > 8 ? 55 : 130);
    };
    entry.timer = setTimeout(repeat, 420);
  });
}

// Listening on the window, not the button: a finger that slides off the key
// still has to stop the repeat - but only its own. blur and visibilitychange
// are the same guards the life counter carries: a press that ends while the
// kiosk is switching away never delivers a pointerup at all.
window.addEventListener("pointerup", (event) => stopHordeRepeat(event.pointerId));
window.addEventListener("pointercancel", (event) => stopHordeRepeat(event.pointerId));
window.addEventListener("blur", stopAllHordeRepeats);
document.addEventListener("visibilitychange", stopAllHordeRepeats);

function buildHordePlayers() {
  // The tiles about to be thrown away may have a finger on them. Their repeats
  // would survive into the game being built here and keep adjusting it.
  stopAllHordeRepeats();
  hordeUi.playersEl.innerHTML = "";
  hordeUi.playersEl.className = "horde-players horde-players--" + hordeGame.players.length;
  hordeUi.playerNodes = [];
  hordeGame.players.forEach((player, index) => {
    const tile = hordeEl("div", "horde-player");
    const minus = hordeButton("horde-step", "−");
    const centre = hordeEl("div", "horde-player-centre");
    const name = hordeEl("div", "horde-player-name", player.name);
    const life = hordeEl("div", "horde-player-life", String(player.life));
    const plus = hordeButton("horde-step", "+");
    attachHordeStepper(minus, index, -1);
    attachHordeStepper(plus, index, 1);
    centre.appendChild(name);
    centre.appendChild(life);
    tile.appendChild(minus);
    tile.appendChild(centre);
    tile.appendChild(plus);
    hordeUi.playersEl.appendChild(tile);
    hordeUi.playerNodes.push({ tile: tile, name: name, life: life });
  });
}

// Updated in place rather than rebuilt: rebuilding would destroy the button
// under a finger that is mid-hold, and its pointerup would never arrive.
function updateHordePlayers() {
  hordeGame.players.forEach((player, index) => {
    const node = hordeUi.playerNodes[index];
    if (!node) return;
    const out = player.life <= 0;
    node.life.textContent = String(player.life);
    node.name.textContent = out ? player.name + " · out" : player.name;
    node.tile.classList.toggle("horde-player--out", out);
    node.tile.classList.toggle("horde-player--low", !out && player.life <= 5);
  });
}

// The creature object is closed over rather than its index: the panel resolves
// the index at the moment an action is taken, so a tile built before a removal
// can never point at whatever slid into its old slot.
function createHordeCreatureTile(creature, animate) {
  const tile = hordeButton("horde-creature", null, () => openHordeCardPanel(creature));
  const token = hordeIsToken(creature);
  if (token) tile.classList.add("horde-creature--token");
  if (creature.neu) tile.classList.add("horde-creature--new");
  if (animate) tile.classList.add("horde-creature--reveal");
  tile.appendChild(hordeEl("span", "horde-creature-name", creature.name));
  const foot = hordeEl("div", "horde-creature-foot");
  if (token) foot.appendChild(hordeEl("span", "horde-creature-tag", "Token"));
  foot.appendChild(hordeEl("span", "horde-creature-pt", hordeFormatPT(creature)));
  tile.appendChild(foot);
  return tile;
}

function renderHordeBattlefield() {
  // Rebuilding the grid empties the scroll container, so the offset is put back
  // by hand: losing your place in a thirty-creature battlefield every time you
  // killed something would make the list unusable.
  const offset = hordeUi.fieldScroll.scrollTop;
  hordeUi.fieldGrid.innerHTML = "";
  hordeGame.battlefield.forEach((creature) => {
    hordeUi.fieldGrid.appendChild(createHordeCreatureTile(creature, false));
  });
  hordeUi.fieldEmpty.classList.toggle("hidden", hordeGame.battlefield.length > 0);
  hordeUi.fieldScroll.scrollTop = offset;
}

function hordePowerTier(power) {
  if (power >= 20) return "danger";
  if (power >= 10) return "warn";
  if (power > 0) return "on";
  return "off";
}

function updateHordeStats() {
  const power = hordeTotalPower();
  const variable = hordeGame.battlefield.some(hordeHasVariablePower);
  const empty = hordeGame.library.length === 0;
  hordeUi.gameTitle.textContent = hordeGame.subtype + " horde";
  hordeUi.gameMeta.textContent = hordeCapitalise(hordeGame.difficulty) + " · " + hordeGame.players.length +
    (hordeGame.players.length === 1 ? " player · Turn " : " players · Turn ") + hordeGame.turn;
  hordeUi.libraryStat.value.textContent = String(hordeGame.library.length);
  // "+*" keeps the total honest when something on the battlefield has a power
  // like "*" that contributes an unknown amount.
  hordeUi.powerStat.value.textContent = String(power) + (variable ? "+*" : "");
  hordeUi.powerStat.el.className = "horde-stat horde-stat--" + hordePowerTier(power);
  hordeUi.fieldTitle.textContent = "Battlefield · " + hordeGame.battlefield.length +
    (hordeGame.battlefield.length === 1 ? " creature" : " creatures");
  hordeUi.turnButton.disabled = empty || !!hordeGame.over;
  hordeUi.turnLabel.textContent = empty ? "Library empty" : "Horde turn";
  hordeUi.turnDetail.textContent = empty
    ? "Finish what's left"
    : "Reveal " + Math.min(hordeGame.cardsPerTurn, hordeGame.library.length);
}

function updateHordeUndo() {
  if (hordeUndo) {
    hordeUi.undoButton.textContent = "↩ " + hordeUndo.creature.name;
    hordeUi.undoButton.classList.remove("hidden");
  } else {
    hordeUi.undoButton.classList.add("hidden");
  }
}

function takeHordeTurn() {
  if (!hordeGame || hordeGame.over || hordeGame.library.length === 0) return;
  hordeUi.fieldGrid.querySelectorAll(".horde-creature--new").forEach((tile) => {
    tile.classList.remove("horde-creature--new");
  });
  hordeGame.battlefield.forEach((creature) => { creature.neu = false; });
  const revealed = hordeGame.library.splice(0, hordeGame.cardsPerTurn);
  revealed.forEach((creature) => {
    creature.neu = true;
    hordeGame.battlefield.push(creature);
    // Appending only the new tiles means the reveal animation plays on those
    // and nothing else flickers.
    hordeUi.fieldGrid.appendChild(createHordeCreatureTile(creature, true));
  });
  hordeGame.turn += 1;
  hordeUndo = null;
  hordeUi.fieldEmpty.classList.add("hidden");
  updateHordeStats();
  updateHordeUndo();
  saveHordeGame();
  requestAnimationFrame(() => {
    hordeUi.fieldScroll.scrollTo({ top: hordeUi.fieldScroll.scrollHeight, behavior: "smooth" });
  });
}

function removeHordeCreature(index) {
  if (!hordeGame || hordeGame.over) return;
  if (index < 0 || index >= hordeGame.battlefield.length) return;
  const removed = hordeGame.battlefield.splice(index, 1)[0];
  // Killing a creature is a single confirm-free tap, which is right for the
  // pace of the format but unforgiving on a two-point touchscreen, so the last
  // removal stays undoable until the next thing happens.
  hordeUndo = { creature: removed, index: index };
  renderHordeBattlefield();
  updateHordeStats();
  updateHordeUndo();
  saveHordeGame();
  checkHordeOutcome();
}

function undoHordeRemoval() {
  if (!hordeGame || !hordeUndo) return;
  const index = Math.min(hordeUndo.index, hordeGame.battlefield.length);
  hordeGame.battlefield.splice(index, 0, hordeUndo.creature);
  hordeUndo = null;
  if (hordeGame.over === "players") {
    hordeGame.over = null;
    hideHordeOverlay();
  }
  renderHordeBattlefield();
  updateHordeStats();
  updateHordeUndo();
  saveHordeGame();
}

function adjustHordeLife(index, delta) {
  if (!hordeGame || hordeGame.over) return;
  const player = hordeGame.players[index];
  if (!player) return;
  player.life = Math.max(-99, Math.min(999, player.life + delta));
  updateHordePlayers();
  saveHordeGame();
  checkHordeOutcome();
}

/* ---------- creature panel: view the card, or remove it ---------- */

// Tapping a creature used to kill it outright. It now opens this panel, because
// horde creatures carry real abilities that decide the turn and looking them up
// on a phone mid-game is the errand this device exists to remove. Removal stays
// two taps, which is still cheap enough for something done constantly, and the
// one-level undo behind it is unchanged.

function buildHordeCardPanel() {
  const overlay = hordeEl("div", "horde-modal horde-card-overlay hidden");
  // The scrim is a dismiss target in its own right: on a screen this size the
  // panel leaves a wide margin, and tapping beside it is the fastest way out.
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeHordeCardPanel();
  });

  const panel = hordeEl("div", "horde-card-panel");

  const head = hordeEl("div", "horde-card-head");
  const heading = hordeEl("div", "horde-card-heading");
  hordeUi.cardName = hordeEl("h3", "horde-card-name", "");
  hordeUi.cardSub = hordeEl("div", "horde-card-sub", "");
  heading.appendChild(hordeUi.cardName);
  heading.appendChild(hordeUi.cardSub);
  hordeUi.cardPT = hordeEl("div", "horde-card-pt", "");
  head.appendChild(heading);
  head.appendChild(hordeUi.cardPT);
  panel.appendChild(head);

  hordeUi.cardBody = hordeEl("div", "horde-card-body");
  hordeUi.cardArt = hordeEl("div", "horde-card-art");
  hordeUi.cardInfo = hordeEl("div", "horde-card-info");
  hordeUi.cardBody.appendChild(hordeUi.cardArt);
  hordeUi.cardBody.appendChild(hordeUi.cardInfo);
  panel.appendChild(hordeUi.cardBody);

  const actions = hordeEl("div", "horde-card-actions");
  hordeUi.cardViewButton = hordeButton("horde-card-button", "View card", viewHordeCardDetail);
  actions.appendChild(hordeUi.cardViewButton);
  actions.appendChild(hordeButton("horde-card-button horde-card-button--remove", "Remove", removeHordeCardPanelCreature));
  actions.appendChild(hordeButton("horde-card-button", "Close", closeHordeCardPanel));
  panel.appendChild(actions);

  overlay.appendChild(panel);
  hordeUi.cardOverlay = overlay;
  return overlay;
}

function openHordeCardPanel(creature) {
  if (!hordeGame || hordeGame.over) return;
  hordeDetailToken += 1;
  hordeCardPanel = { creature: creature, mode: "menu", detail: null };
  renderHordeCardPanel();
  hordeUi.cardOverlay.classList.remove("hidden");
}

function closeHordeCardPanel() {
  // Bumping on close is what stops a reply that is already on the wire from
  // painting into a panel nobody is looking at any more.
  hordeDetailToken += 1;
  hordeCardPanel = null;
  if (hordeUi.cardOverlay) hordeUi.cardOverlay.classList.add("hidden");
}

function viewHordeCardDetail() {
  if (!hordeCardPanel) return;
  hordeCardPanel.mode = "detail";
  renderHordeCardPanel();
  loadHordeCardDetail(hordeCardPanel);
}

function removeHordeCardPanelCreature() {
  if (!hordeGame || !hordeCardPanel) return;
  // Resolved now rather than when the tile was built, so a battlefield that has
  // shifted underneath the panel still removes the creature that was tapped.
  const index = hordeGame.battlefield.indexOf(hordeCardPanel.creature);
  closeHordeCardPanel();
  if (index === -1) return;
  removeHordeCreature(index);
}

function renderHordeCardPanel() {
  if (!hordeCardPanel) return;
  const creature = hordeCardPanel.creature;
  const token = hordeIsToken(creature);
  const detail = hordeCardPanel.mode === "detail";
  hordeUi.cardName.textContent = creature.name;
  hordeUi.cardSub.textContent = token ? "Token · on the battlefield" : "On the battlefield";
  hordeUi.cardPT.textContent = hordeFormatPT(creature);
  // Hiding the body is what turns the panel from a compact action sheet into
  // the full card view; the panel is a column flexbox, so it collapses to the
  // header and buttons on its own.
  hordeUi.cardBody.classList.toggle("hidden", !detail);
  hordeUi.cardViewButton.classList.toggle("hidden", detail);
  hordeUi.cardViewButton.textContent = token ? "View" : "View card";
  if (detail) renderHordeCardDetail();
}

// A missing image is the normal offline case, not a failure: the endpoint 404s
// when it has no art cached and can't reach Scryfall, so "no art exists" and
// "no network" land on the same quiet placeholder rather than a broken image.
function renderHordeCardArt(card, token) {
  hordeUi.cardArt.innerHTML = "";
  const note = hordeEl("div", "horde-card-art-note", card.has_image ? "Loading image…" : "No image");
  hordeUi.cardArt.appendChild(note);
  if (!card.has_image || typeof card.id !== "string" || !card.id) return;
  const image = hordeEl("img", "horde-card-photo");
  image.alt = "";
  image.addEventListener("load", () => {
    if (hordeDetailToken !== token) return;
    note.classList.add("hidden");
    image.classList.add("horde-card-photo--on");
  });
  image.addEventListener("error", () => {
    if (hordeDetailToken !== token) return;
    image.remove();
    note.textContent = "No image";
  });
  image.src = "/api/cards/" + encodeURIComponent(card.id) + "/image";
  hordeUi.cardArt.appendChild(image);
}

function renderHordeCardDetail() {
  const entry = hordeCardPanel;
  if (!entry) return;
  const state = entry.detail ? entry.detail.state : "loading";
  hordeUi.cardInfo.innerHTML = "";
  hordeUi.cardArt.innerHTML = "";

  if (state === "loading") {
    hordeUi.cardArt.appendChild(hordeEl("div", "horde-card-art-note", "…"));
    hordeUi.cardInfo.appendChild(hordeEl("p", "horde-card-note", "Reading the card…"));
    return;
  }

  // No card id: a player-made token, or a deck entry that arrived without one.
  // Everything known about it is already on screen, so say so plainly instead
  // of asking the server about a card that does not exist.
  if (state === "none") {
    hordeUi.cardArt.appendChild(hordeEl("div", "horde-card-art-note", "No image"));
    hordeUi.cardInfo.appendChild(hordeEl("div", "horde-card-type",
      hordeIsToken(entry.creature) ? "Token creature — " + entry.creature.name : "Creature"));
    hordeUi.cardInfo.appendChild(hordeEl("p", "horde-card-rules",
      hordeIsToken(entry.creature)
        ? "A token you put onto the battlefield. It has no rules text of its own and counts towards Horde power like any other creature."
        : "This creature came without a card id, so there is nothing to look up. Its name and power/toughness are above."));
    return;
  }

  if (state === "error") {
    hordeUi.cardArt.appendChild(hordeEl("div", "horde-card-art-note", "No image"));
    hordeUi.cardInfo.appendChild(hordeEl("p", "horde-card-note", "Couldn't read this card."));
    if (entry.detail.message) {
      hordeUi.cardInfo.appendChild(hordeEl("p", "horde-card-note horde-card-note--quiet", entry.detail.message));
    }
    return;
  }

  const card = entry.detail.card;
  renderHordeCardArt(card, entry.detail.token);
  const typeLine = card.type_line || "Creature";
  const header = hordeEl("div", "horde-card-typerow");
  header.appendChild(hordeEl("span", "horde-card-type", typeLine));
  if (card.mana_cost) header.appendChild(hordeEl("span", "horde-card-cost", card.mana_cost));
  hordeUi.cardInfo.appendChild(header);
  const rules = card.oracle_text ? String(card.oracle_text) : "";
  hordeUi.cardInfo.appendChild(hordeEl("p", "horde-card-rules" + (rules ? "" : " horde-card-rules--none"),
    rules || "No rules text."));
  const meta = [card.set_name, card.rarity ? hordeCapitalise(card.rarity) : null].filter(Boolean).join(" · ");
  if (meta) hordeUi.cardInfo.appendChild(hordeEl("p", "horde-card-note horde-card-note--quiet", meta));
}

// The persisted deck keeps only id/name/power/toughness so the localStorage
// write on every life tap stays cheap. Rules text is fetched here instead, and
// /api/cards/{id} is a local SQLite read, so it answers with no network.
async function loadHordeCardDetail(entry) {
  const creature = entry.creature;
  const id = typeof creature.id === "string" ? creature.id : "";
  if (!id) {
    entry.detail = { state: "none" };
    if (hordeCardPanel === entry) renderHordeCardDetail();
    return;
  }
  const token = ++hordeDetailToken;
  const cached = hordeDetailCache.get(id);
  if (cached) {
    entry.detail = { state: "ready", card: cached, token: token };
    if (hordeCardPanel === entry) renderHordeCardDetail();
    return;
  }
  entry.detail = { state: "loading", token: token };
  if (hordeCardPanel === entry) renderHordeCardDetail();
  try {
    const response = await fetch("/api/cards/" + encodeURIComponent(id));
    // Two guards, both load-bearing: the token catches a panel that has since
    // been closed or switched card, and the identity check catches a panel
    // reopened on the same creature while this was in flight.
    if (hordeDetailToken !== token || hordeCardPanel !== entry) return;
    if (!response.ok) {
      entry.detail = { state: "error", message: "The device answered with HTTP " + response.status + ".", token: token };
      renderHordeCardDetail();
      return;
    }
    const card = await response.json();
    if (hordeDetailToken !== token || hordeCardPanel !== entry) return;
    if (!card || typeof card !== "object") {
      entry.detail = { state: "error", message: "", token: token };
      renderHordeCardDetail();
      return;
    }
    hordeDetailCache.set(id, card);
    entry.detail = { state: "ready", card: card, token: token };
    renderHordeCardDetail();
  } catch (err) {
    if (hordeDetailToken !== token || hordeCardPanel !== entry) return;
    entry.detail = { state: "error", message: firstLine(err.message), token: token };
    renderHordeCardDetail();
  }
}

/* ---------- tokens ---------- */

// Real cards make tokens - "create two 1/1 white Soldier creature tokens" - and
// the horde's board has to carry them or the power total is wrong. They are
// ordinary battlefield entries, so they total, remove and undo through the same
// code paths as revealed cards.

function hordeTokenDefaults() {
  return { name: hordeGame ? hordeGame.subtype : "Token", power: 1, toughness: 1, count: 1 };
}

function buildHordeTokenStepper(label, key, min, max) {
  const group = hordeEl("div", "horde-token-field");
  group.appendChild(hordeEl("div", "horde-label", label));
  const row = hordeEl("div", "horde-token-stepper");
  const down = hordeButton("horde-token-step", "−", () => adjustHordeTokenValue(key, -1, min, max));
  const value = hordeEl("div", "horde-token-value", "1");
  const up = hordeButton("horde-token-step", "+", () => adjustHordeTokenValue(key, 1, min, max));
  row.appendChild(down);
  row.appendChild(value);
  row.appendChild(up);
  group.appendChild(row);
  hordeUi.tokenValues[key] = value;
  return group;
}

function adjustHordeTokenValue(key, delta, min, max) {
  if (!hordeTokenDraft) return;
  hordeTokenDraft[key] = Math.max(min, Math.min(max, hordeTokenDraft[key] + delta));
  updateHordeTokenDialog();
}

function buildHordeTokenDialog() {
  const overlay = hordeEl("div", "horde-modal horde-token-overlay hidden");
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeHordeTokenDialog();
  });

  const panel = hordeEl("div", "horde-token-panel");
  panel.appendChild(hordeEl("h3", "horde-token-title", "Add tokens"));

  const nameField = hordeEl("div", "horde-token-field");
  nameField.appendChild(hordeEl("div", "horde-label", "Name"));
  const nameRow = hordeEl("div", "horde-token-name-row");
  hordeUi.tokenName = hordeEl("input", "horde-token-input");
  hordeUi.tokenName.type = "text";
  hordeUi.tokenName.setAttribute("autocomplete", "off");
  hordeUi.tokenName.setAttribute("spellcheck", "false");
  // There is no hardware keyboard on this device, so the shared on-screen one
  // is the only way to change the name off the horde's own subtype.
  hordeUi.tokenName.addEventListener("click", () => setHordeTokenTyping(true));
  hordeUi.tokenName.addEventListener("input", () => {
    if (hordeTokenDraft) hordeTokenDraft.name = hordeUi.tokenName.value;
  });
  // Only one of the pair is ever on screen; which one is decided in CSS by the
  // typing class, so neither needs a handle here.
  nameRow.appendChild(hordeUi.tokenName);
  nameRow.appendChild(hordeButton("horde-token-keyboard", "Keyboard", () => setHordeTokenTyping(true)));
  nameRow.appendChild(hordeButton("horde-token-done", "Done", () => setHordeTokenTyping(false)));
  nameField.appendChild(nameRow);
  panel.appendChild(nameField);

  hordeUi.tokenValues = {};
  const numbers = hordeEl("div", "horde-token-numbers");
  numbers.appendChild(buildHordeTokenStepper("Power", "power", 0, HORDE_TOKEN_MAX_PT));
  numbers.appendChild(buildHordeTokenStepper("Toughness", "toughness", 0, HORDE_TOKEN_MAX_PT));
  numbers.appendChild(buildHordeTokenStepper("How many", "count", 1, HORDE_TOKEN_MAX_COUNT));
  panel.appendChild(numbers);

  const actions = hordeEl("div", "horde-token-actions");
  actions.appendChild(hordeButton("horde-card-button", "Cancel", closeHordeTokenDialog));
  hordeUi.tokenAddButton = hordeButton("horde-card-button horde-card-button--primary", "Add", addHordeTokens);
  actions.appendChild(hordeUi.tokenAddButton);
  panel.appendChild(actions);

  overlay.appendChild(panel);
  hordeUi.tokenOverlay = overlay;
  hordeUi.tokenPanel = panel;
  return overlay;
}

function updateHordeTokenDialog() {
  if (!hordeTokenDraft) return;
  hordeUi.tokenValues.power.textContent = String(hordeTokenDraft.power);
  hordeUi.tokenValues.toughness.textContent = String(hordeTokenDraft.toughness);
  hordeUi.tokenValues.count.textContent = String(hordeTokenDraft.count);
  hordeUi.tokenAddButton.textContent = hordeTokenDraft.count === 1
    ? "Add 1 token"
    : "Add " + hordeTokenDraft.count + " tokens";
}

// While the on-screen keyboard is up it owns the bottom ~256px of the screen,
// so the dialog moves to the top and drops to just the name row. The overlay
// also gives up its z-index for the duration: it is a positioned element and
// the keyboard is not, so keeping the stacking order would paint the scrim
// over the keys and make them untappable.
function setHordeTokenTyping(on) {
  if (!hordeUi.tokenPanel) return;
  if (!isViewVisible("horde-mode")) return;
  hordeUi.tokenOverlay.classList.toggle("horde-modal--typing", on);
  hordeUi.tokenPanel.classList.toggle("horde-token-panel--typing", on);
  if (on) {
    showKeyboardFor(hordeUi.tokenName);
  } else {
    hideKeyboard();
  }
}

function openHordeTokenDialog() {
  if (!hordeGame || hordeGame.over) return;
  closeHordeCardPanel();
  if (!hordeTokenDraft) hordeTokenDraft = hordeTokenDefaults();
  hordeUi.tokenName.value = hordeTokenDraft.name;
  updateHordeTokenDialog();
  hordeUi.tokenOverlay.classList.remove("hidden");
  setHordeTokenTyping(false);
}

function closeHordeTokenDialog() {
  if (!hordeUi.tokenOverlay) return;
  setHordeTokenTyping(false);
  hordeUi.tokenOverlay.classList.add("hidden");
}

function addHordeTokens() {
  if (!hordeGame || hordeGame.over || !hordeTokenDraft) return;
  const name = String(hordeUi.tokenName.value || "").trim() || hordeGame.subtype || "Token";
  hordeTokenDraft.name = name;
  const count = Math.max(1, Math.min(HORDE_TOKEN_MAX_COUNT, hordeTokenDraft.count));
  closeHordeTokenDialog();
  for (let i = 0; i < count; i += 1) {
    const token = hordeMakeToken(name, hordeTokenDraft.power, hordeTokenDraft.toughness);
    token.neu = true;
    hordeGame.battlefield.push(token);
    hordeUi.fieldGrid.appendChild(createHordeCreatureTile(token, true));
  }
  // Adding is "the next thing that happened", same as a horde turn, so the
  // pending undo of an earlier removal expires with it.
  hordeUndo = null;
  hordeUi.fieldEmpty.classList.add("hidden");
  updateHordeStats();
  updateHordeUndo();
  saveHordeGame();
  requestAnimationFrame(() => {
    hordeUi.fieldScroll.scrollTo({ top: hordeUi.fieldScroll.scrollHeight, behavior: "smooth" });
  });
}

/* ---------- outcome ---------- */

function checkHordeOutcome() {
  if (!hordeGame || hordeGame.over) return;
  if (hordeGame.players.every((player) => player.life <= 0)) {
    hordeGame.over = "horde";
  } else if (hordeGame.library.length === 0 && hordeGame.battlefield.length === 0) {
    hordeGame.over = "players";
  }
  if (!hordeGame.over) return;
  updateHordeStats();
  saveHordeGame();
  showHordeOutcome();
}

function showHordeOutcome() {
  const won = hordeGame.over === "players";
  showHordeOverlay(
    won ? "win" : "lose",
    won ? "The horde is destroyed" : "The horde wins",
    won
      ? "Its library and its battlefield are empty. You held out for " + hordeGame.turn + " turns."
      : "Every player is at zero. The horde ran the table on turn " + hordeGame.turn + ".",
    [
      { label: "Keep playing", onClick: resumeHordeGame },
      { label: "Back to menu", onClick: () => { abandonHordeGame(); showView("menu"); } },
      { label: "New game", primary: true, onClick: abandonHordeGame },
    ]
  );
}

function resumeHordeGame() {
  if (!hordeGame) return;
  hordeGame.over = null;
  hideHordeOverlay();
  updateHordeStats();
  saveHordeGame();
}

function confirmAbandonHorde() {
  showHordeOverlay(
    "confirm",
    "End this game?",
    "The horde deck and every life total will be thrown away.",
    [
      { label: "Keep playing", onClick: hideHordeOverlay },
      { label: "End game", primary: true, onClick: abandonHordeGame },
    ]
  );
}

function abandonHordeGame() {
  stopAllHordeRepeats();
  closeHordeCardPanel();
  closeHordeTokenDialog();
  hordeGame = null;
  hordeUndo = null;
  // The next game is a different deck and a different subtype, so neither the
  // looked-up card text nor the remembered token stays useful.
  hordeDetailCache.clear();
  hordeTokenDraft = null;
  saveHordeGame();
  hideHordeOverlay();
  showHordeScreen("setup");
  if (hordeSubtypesState !== "ready") loadHordeSubtypes();
}

/* ---------- overlay and screen switching ---------- */

function buildHordeOverlay() {
  const overlay = hordeEl("div", "horde-overlay hidden");
  const panel = hordeEl("div", "horde-overlay-panel");
  hordeUi.overlayTitle = hordeEl("h2", "horde-overlay-title", "");
  hordeUi.overlayMessage = hordeEl("p", "horde-overlay-message", "");
  hordeUi.overlayActions = hordeEl("div", "horde-overlay-actions");
  panel.appendChild(hordeUi.overlayTitle);
  panel.appendChild(hordeUi.overlayMessage);
  panel.appendChild(hordeUi.overlayActions);
  overlay.appendChild(panel);
  hordeUi.overlay = overlay;
  return overlay;
}

function showHordeOverlay(kind, title, message, actions) {
  // The outcome and confirm overlay is the only thing that should be on screen
  // once it appears, and both of the newer panels sit above it.
  closeHordeCardPanel();
  closeHordeTokenDialog();
  hordeUi.overlayTitle.textContent = title;
  hordeUi.overlayMessage.textContent = message;
  hordeUi.overlayActions.innerHTML = "";
  actions.forEach((action) => {
    hordeUi.overlayActions.appendChild(hordeButton(
      "horde-overlay-button" + (action.primary ? " horde-overlay-button--primary" : ""),
      action.label,
      action.onClick
    ));
  });
  hordeUi.overlay.className = "horde-overlay horde-overlay--" + kind;
}

function hideHordeOverlay() {
  hordeUi.overlay.classList.add("hidden");
}

function showHordeScreen(name) {
  hordeUi.setup.classList.toggle("hidden", name !== "setup");
  hordeUi.game.classList.toggle("hidden", name !== "game");
}

function enterHordeGame() {
  hordeUndo = null;
  closeHordeCardPanel();
  closeHordeTokenDialog();
  buildHordePlayers();
  renderHordeBattlefield();
  updateHordePlayers();
  updateHordeStats();
  updateHordeUndo();
  showHordeScreen("game");
  if (hordeGame.over) showHordeOutcome();
  else hideHordeOverlay();
}

// Nothing else notices the view going away, and a stepper held while the player
// taps Menu with a second finger never gets a pointerup on this screen. The two
// panels are torn down here for the same reason: closing invalidates any detail
// fetch still on the wire, and the token dialog otherwise leaves the shared
// on-screen keyboard up over whatever view comes next.
function onHordeHidden() {
  stopAllHordeRepeats();
  closeHordeCardPanel();
  if (hordeUi.tokenOverlay) {
    // Not closeHordeTokenDialog(): its keyboard call is gated on this view
    // still being visible, and by now it isn't. showView() has already put the
    // keyboard away itself, so only the overlay needs hiding.
    hordeUi.tokenOverlay.classList.remove("horde-modal--typing");
    hordeUi.tokenPanel.classList.remove("horde-token-panel--typing");
    hordeUi.tokenOverlay.classList.add("hidden");
  }
}

function onHordeShown() {
  if (!hordeUi.root) return;
  if (hordeGame) {
    enterHordeGame();
    return;
  }
  hideHordeOverlay();
  showHordeScreen("setup");
  // Retried on every visit while it has failed: the player may have just
  // downloaded the database from Settings and come straight back.
  if (hordeSubtypesState !== "ready") loadHordeSubtypes();
}

function buildHordeUi() {
  const root = document.getElementById("horde-root");
  if (!root) return;
  hordeUi.root = root;
  root.innerHTML = "";
  hordeUi.setup = buildHordeSetupScreen();
  hordeUi.game = buildHordeGameScreen();
  hordeUi.game.classList.add("hidden");
  root.appendChild(hordeUi.setup);
  root.appendChild(hordeUi.game);
  root.appendChild(buildHordeOverlay());
  root.appendChild(buildHordeCardPanel());
  root.appendChild(buildHordeTokenDialog());
  hordeUi.startButton.disabled = true;
  restoreHordeGame();
  if (hordeGame) enterHordeGame();
}

buildHordeUi();
