/* Slice 2 (random card) and Slice 4 (card lookup).

   One IIFE that exports only the two entry points the shell calls. This file
   shares a global scope with app.js, lifecounter.js and horde.js, so
   top-level helpers named make() or runSearch() would be a name collision
   waiting to happen. */
(function () {
  "use strict";

  const randomRoot = document.getElementById("random-card-root");
  const lookupRoot = document.getElementById("card-lookup-root");
  if (!randomRoot || !lookupRoot) {
    console.error("cards.js: #random-card-root / #card-lookup-root are missing");
    return;
  }

  const SEARCH_DEBOUNCE_MS = 250;
  const MANA_CLASSES = { W: "w", U: "u", B: "b", R: "r", G: "g", C: "c" };
  const COLOR_NAMES = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green" };

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function makeButton(label, className) {
    const node = make("button", className, label);
    node.type = "button";
    return node;
  }

  // ---------------------------------------------------------------- card bits

  function manaPip(symbol) {
    // Scryfall writes hybrid and Phyrexian mana as "W/U", "2/W", "W/P".
    const letters = symbol.replace(/\//g, "");
    const pip = make("span", "mana-pip", letters);
    const colors = letters.split("").filter((letter) => MANA_CLASSES[letter]);
    if (colors.length === 1) {
      pip.classList.add("mana-" + MANA_CLASSES[colors[0]]);
    } else if (colors.length > 1) {
      pip.classList.add("mana-hybrid");
      pip.style.setProperty("--pip-a", "var(--mana-" + MANA_CLASSES[colors[0]] + ")");
      pip.style.setProperty("--pip-b", "var(--mana-" + MANA_CLASSES[colors[1]] + ")");
    }
    return pip;
  }

  /* Card text is riddled with {T}, {2}, {W} - rendering those as pips is what
     makes a cost read as a cost instead of as punctuation. */
  function appendSymbols(parent, text) {
    const pattern = /\{([^}]{1,6})\}/g;
    let index = 0;
    let match = pattern.exec(text);
    while (match !== null) {
      if (match.index > index) {
        parent.appendChild(document.createTextNode(text.slice(index, match.index)));
      }
      parent.appendChild(manaPip(match[1]));
      index = match.index + match[0].length;
      match = pattern.exec(text);
    }
    if (index < text.length) {
      parent.appendChild(document.createTextNode(text.slice(index)));
    }
  }

  /* One paragraph per line, because a card's abilities are separate rules and
     run together illegibly when they are only separated by a line break.
     Ingest joins the faces of a double-faced card with a "//" line. */
  function appendRules(parent, text) {
    text.split("\n").forEach((line) => {
      if (line.trim() === "//") {
        parent.appendChild(make("div", "card-rules-break"));
        return;
      }
      if (!line.trim()) return;
      const paragraph = make("p", "card-rules-line");
      appendSymbols(paragraph, line);
      parent.appendChild(paragraph);
    });
  }

  function setLabel(card) {
    const name = card.set_name || "";
    const code = card.set_code ? card.set_code.toUpperCase() : "";
    if (name && code) return name + " (" + code + ")";
    return name || code || "Unknown set";
  }

  function colorLabel(colors) {
    if (!colors) return "Colorless";
    const names = colors
      .split(",")
      .map((letter) => COLOR_NAMES[letter.trim()])
      .filter(Boolean);
    return names.length ? names.join(", ") : "Colorless";
  }

  function metaLabel(card) {
    const parts = [];
    if (typeof card.cmc === "number") {
      // Mana value is a whole number on all but a handful of joke cards.
      parts.push("Mana value " + (Number.isInteger(card.cmc) ? card.cmc : card.cmc.toFixed(1)));
    }
    parts.push(colorLabel(card.colors));
    return parts.join("  ·  ");
  }

  /* Ingest flattens a double-faced card into power "2 // 4", toughness
     "2 // 4". Zipping the faces back together reads as "2/2 // 4/4" instead
     of the meaningless "2 // 4/2 // 4". */
  function statLabel(power, toughness) {
    const powers = power.split("//").map((part) => part.trim());
    const toughnesses = toughness.split("//").map((part) => part.trim());
    if (powers.length > 1 && powers.length === toughnesses.length) {
      return powers.map((value, face) => value + "/" + toughnesses[face]).join(" // ");
    }
    return power + "/" + toughness;
  }

  function appendStat(foot, card) {
    const hasPower = card.power !== null && card.power !== undefined && card.power !== "";
    const hasToughness = card.toughness !== null && card.toughness !== undefined && card.toughness !== "";
    if (hasPower && hasToughness) {
      foot.appendChild(make("span", "card-stat", statLabel(card.power, card.toughness)));
    } else if (card.loyalty) {
      foot.appendChild(make("span", "card-stat card-stat-loyalty", card.loyalty));
    }
  }

  function cardPanel(card, detailed) {
    const panel = make("div", "card-panel");

    const head = make("div", "card-head");
    head.appendChild(make("h2", "card-name", card.name || "Unknown card"));
    if (card.mana_cost) {
      const cost = make("div", "card-cost");
      appendSymbols(cost, card.mana_cost);
      head.appendChild(cost);
    }
    panel.appendChild(head);

    panel.appendChild(make("div", "card-type", card.type_line || "—"));
    if (detailed) {
      panel.appendChild(make("div", "card-meta", metaLabel(card)));
    }

    const rules = make("div", "card-rules");
    if (card.oracle_text) {
      appendRules(rules, card.oracle_text);
    } else {
      // A vanilla creature really has an empty text box; say so rather than
      // leaving a blank area that reads like a failed load.
      rules.appendChild(make("p", "card-rules-empty", "No rules text."));
    }
    panel.appendChild(rules);

    const foot = make("div", "card-foot");
    foot.appendChild(make("span", "card-set", setLabel(card)));
    if (card.rarity) {
      const rarity = String(card.rarity).replace(/[^a-z]/gi, "").toLowerCase();
      foot.appendChild(make("span", "card-rarity rarity-" + rarity, card.rarity));
    }
    appendStat(foot, card);
    panel.appendChild(foot);

    return panel;
  }

  // ------------------------------------------------------------ shared plumbing

  async function fetchCardsStatus() {
    try {
      const response = await fetch("/api/cards/status");
      if (!response.ok) return null;
      return await response.json();
    } catch (err) {
      return null;
    }
  }

  function progressLabel(progress) {
    if (!progress) return "";
    const stage = typeof progress.stage === "string" ? progress.stage : "";
    const done = typeof progress.done === "number" ? progress.done : null;
    const total = typeof progress.total === "number" && progress.total > 0 ? progress.total : null;
    if (done !== null && total !== null) {
      return (stage + " " + done.toLocaleString() + " of " + total.toLocaleString()).trim();
    }
    if (done !== null) return (stage + " " + done.toLocaleString()).trim();
    return stage;
  }

  /* A fresh install genuinely has no card database, so "missing" is a normal
     state with a next step, not an error. Returns null when the database is
     fine and the caller's own failure message should win. */
  function describeStatus(status, purpose) {
    // An available database stays usable during a refresh - ingest builds a
    // temp file and renames it - so `updating` alone must not lock the screen.
    if (!status || status.available !== false) return null;
    if (status.updating) {
      return {
        title: "Downloading the card database…",
        body: progressLabel(status.progress) || "This takes a few minutes. Come back shortly.",
        retryLabel: "Check again",
      };
    }
    return {
      title: "No card database yet",
      body: "Open Settings and download the card database to " + purpose + ".",
      retryLabel: "Try again",
    };
  }

  function buildNotice(onRetry) {
    const root = make("div", "cards-notice hidden");
    const inner = make("div", "cards-notice-inner");
    const title = make("h2", "cards-notice-title");
    const body = make("p", "cards-notice-body");
    const actions = make("div", "cards-notice-actions");

    const settingsButton = makeButton("Open Settings", "cards-button cards-button-primary");
    settingsButton.addEventListener("click", () => showView("settings"));
    const retryButton = makeButton("Try again", "cards-button");
    retryButton.addEventListener("click", onRetry);
    const backButton = makeButton("Menu", "back-button");
    backButton.addEventListener("click", () => showView("menu"));

    actions.appendChild(settingsButton);
    actions.appendChild(retryButton);
    actions.appendChild(backButton);
    inner.appendChild(title);
    inner.appendChild(body);
    inner.appendChild(actions);
    root.appendChild(inner);

    return {
      root,
      show(description) {
        title.textContent = description.title;
        body.textContent = description.body;
        retryButton.textContent = description.retryLabel || "Try again";
        settingsButton.classList.toggle("hidden", description.hideSettings === true);
        root.classList.remove("hidden");
      },
      hide() {
        root.classList.add("hidden");
      },
    };
  }

  /* isStale() is checked after every await: a print started against one card
     must never drop its verdict onto the next card's screen. */
  async function printCard(cardId, statusEl, printButton, isStale) {
    if (!cardId) return;
    printButton.disabled = true;
    setStatus(statusEl, "Printing…", "");
    try {
      const response = await fetch("/api/cards/print", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: cardId }),
      });
      if (isStale()) return;
      if (response.ok) {
        setStatus(statusEl, "Sent to the printer.", "is-ok");
      } else {
        const data = await response.json().catch(() => ({}));
        if (isStale()) return;
        setStatus(statusEl, firstLine(data.detail || "Printer not connected."), "is-bad");
      }
    } catch (err) {
      if (isStale()) return;
      setStatus(statusEl, "Couldn't print: " + firstLine(err.message), "is-bad");
    } finally {
      if (!isStale()) printButton.disabled = false;
    }
  }

  function setStatus(statusEl, text, modifier) {
    statusEl.classList.remove("is-ok", "is-bad");
    if (modifier) statusEl.classList.add(modifier);
    statusEl.textContent = text;
  }

  // ------------------------------------------------------------- random card

  let randomToken = 0;
  let randomCardId = null;

  const randomLayout = make("div", "cards-screen");
  const randomSlot = make("div", "cards-panel-slot");
  const randomActions = make("div", "cards-actions");
  const rollButton = makeButton("Roll again", "cards-button cards-button-primary cards-button-tall");
  const randomPrintButton = makeButton("Print", "cards-button");
  const randomBackButton = makeButton("Menu", "back-button");
  const randomStatus = make("p", "cards-status");
  const randomNotice = buildNotice(() => rollCard());

  randomPrintButton.disabled = true;
  randomActions.appendChild(rollButton);
  randomActions.appendChild(randomPrintButton);
  randomActions.appendChild(randomStatus);
  randomActions.appendChild(randomBackButton);
  randomLayout.appendChild(randomSlot);
  randomLayout.appendChild(randomActions);
  randomRoot.appendChild(randomLayout);
  randomRoot.appendChild(randomNotice.root);

  rollButton.addEventListener("click", () => rollCard());
  randomBackButton.addEventListener("click", () => showView("menu"));
  randomPrintButton.addEventListener("click", () => {
    const cardId = randomCardId;
    printCard(cardId, randomStatus, randomPrintButton, () => randomCardId !== cardId);
  });

  function showRandomNotice(description) {
    randomLayout.classList.add("hidden");
    randomNotice.show(description);
  }

  async function rollCard() {
    const token = ++randomToken;
    randomCardId = null;
    randomPrintButton.disabled = true;
    setStatus(randomStatus, "", "");
    randomNotice.hide();
    randomLayout.classList.remove("hidden");
    randomSlot.classList.add("is-loading");
    if (!randomSlot.firstChild) {
      randomSlot.appendChild(make("div", "card-placeholder", "Rolling…"));
    }
    rollButton.disabled = true;
    try {
      const response = await fetch("/api/cards/random");
      if (randomToken !== token) return;
      if (!response.ok) {
        const status = await fetchCardsStatus();
        if (randomToken !== token) return;
        showRandomNotice(
          describeStatus(status, "roll a random card") || {
            title: "Couldn't roll a card",
            body: "The card database didn't answer (" + response.status + ").",
            hideSettings: true,
          }
        );
        return;
      }
      const card = await response.json();
      if (randomToken !== token) return;
      randomSlot.innerHTML = "";
      randomSlot.appendChild(cardPanel(card, false));
      randomCardId = card.id;
      randomPrintButton.disabled = false;
    } catch (err) {
      if (randomToken !== token) return;
      showRandomNotice({
        title: "Couldn't roll a card",
        body: firstLine(err.message),
        hideSettings: true,
      });
    } finally {
      if (randomToken === token) {
        rollButton.disabled = false;
        randomSlot.classList.remove("is-loading");
      }
    }
  }

  // ------------------------------------------------------------- card lookup

  let searchToken = 0;
  let searchTimer = null;
  let detailToken = 0;
  let detailCardId = null;
  let lookupShowToken = 0;
  let keyboardOpen = false;

  const searchPane = make("div", "cards-screen cards-screen-column");
  const lookupHeader = make("div", "lookup-header");
  const lookupBackButton = makeButton("Menu", "back-button");
  const searchInput = make("input", "lookup-input");
  const clearButton = makeButton("✕", "cards-button lookup-icon-button");
  const keyboardButton = makeButton("Done", "cards-button lookup-keyboard-button");
  const resultsList = make("div", "lookup-results");

  searchInput.type = "text";
  searchInput.placeholder = "Card name";
  searchInput.autocomplete = "off";
  searchInput.spellcheck = false;
  clearButton.title = "Clear";

  lookupHeader.appendChild(lookupBackButton);
  lookupHeader.appendChild(searchInput);
  lookupHeader.appendChild(clearButton);
  lookupHeader.appendChild(keyboardButton);
  searchPane.appendChild(lookupHeader);
  searchPane.appendChild(resultsList);

  const detailPane = make("div", "cards-screen cards-screen-column hidden");
  const detailHeader = make("div", "card-detail-header");
  const detailBackButton = makeButton("‹ Results", "cards-button");
  const detailStatus = make("p", "cards-status card-detail-status");
  const detailPrintButton = makeButton("Print", "cards-button cards-button-primary");
  const detailBody = make("div", "card-detail-body");

  detailHeader.appendChild(detailBackButton);
  detailHeader.appendChild(detailStatus);
  detailHeader.appendChild(detailPrintButton);
  detailPane.appendChild(detailHeader);
  detailPane.appendChild(detailBody);

  const lookupNotice = buildNotice(() => onCardLookupShown());

  lookupRoot.appendChild(searchPane);
  lookupRoot.appendChild(detailPane);
  lookupRoot.appendChild(lookupNotice.root);

  function setKeyboardOpen(open) {
    keyboardOpen = open;
    keyboardButton.textContent = open ? "Done" : "Keyboard";
    if (open) {
      showKeyboardFor(searchInput);
    } else {
      hideKeyboard();
    }
  }

  function showHint(text) {
    resultsList.innerHTML = "";
    resultsList.appendChild(make("p", "lookup-hint", text));
  }

  function scheduleSearch() {
    // Bump the token on every keystroke, not just when a request starts, so a
    // reply already in flight can never repaint a list the user has moved on
    // from.
    searchToken += 1;
    if (searchTimer !== null) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      searchTimer = null;
      runSearch(searchInput.value.trim());
    }, SEARCH_DEBOUNCE_MS);
  }

  async function runSearch(query) {
    const token = ++searchToken;
    if (!query) {
      showHint("Type a card name to search.");
      return;
    }
    try {
      const response = await fetch("/api/cards/search?q=" + encodeURIComponent(query));
      if (searchToken !== token) return;
      if (!response.ok) {
        const status = await fetchCardsStatus();
        if (searchToken !== token) return;
        const description = describeStatus(status, "look cards up");
        if (description) {
          showLookupNotice(description);
        } else {
          showHint("Couldn't search (" + response.status + "). Try again.");
        }
        return;
      }
      const cards = await response.json();
      if (searchToken !== token) return;
      renderResults(cards, query);
    } catch (err) {
      if (searchToken !== token) return;
      showHint("Couldn't search: " + firstLine(err.message));
    }
  }

  function renderResults(cards, query) {
    resultsList.innerHTML = "";
    if (!cards.length) {
      showHint('No cards match "' + query + '".');
      return;
    }
    cards.forEach((card) => {
      const row = makeButton("", "lookup-result");
      row.appendChild(make("span", "lookup-result-name", card.name));
      row.appendChild(make("span", "lookup-result-type", card.type_line || "—"));
      row.addEventListener("click", () => openDetail(card));
      resultsList.appendChild(row);
    });
  }

  function showLookupNotice(description) {
    setKeyboardOpen(false);
    searchPane.classList.add("hidden");
    detailPane.classList.add("hidden");
    lookupNotice.show(description);
  }

  /* A missing image is the normal offline case, not a failure: the endpoint
     404s when it can't reach Scryfall, so both "no image known" and "couldn't
     fetch it" land on the same quiet placeholder. */
  function imageColumn(card, token) {
    const column = make("div", "card-image");
    const placeholder = make("div", "card-image-placeholder", card.has_image ? "Loading image…" : "No image");
    column.appendChild(placeholder);
    if (!card.has_image) return column;

    const image = make("img", "card-image-photo");
    image.alt = "";
    image.addEventListener("load", () => {
      if (detailToken !== token) return;
      placeholder.classList.add("hidden");
      image.classList.add("is-loaded");
    });
    image.addEventListener("error", () => {
      if (detailToken !== token) return;
      image.remove();
      placeholder.textContent = "No image";
    });
    image.src = "/api/cards/" + encodeURIComponent(card.id) + "/image";
    column.appendChild(image);
    return column;
  }

  function openDetail(card) {
    detailToken += 1;
    detailCardId = card.id;
    setKeyboardOpen(false);
    setStatus(detailStatus, "", "");
    detailPrintButton.disabled = false;
    detailBody.innerHTML = "";
    detailBody.appendChild(imageColumn(card, detailToken));
    detailBody.appendChild(cardPanel(card, true));
    searchPane.classList.add("hidden");
    detailPane.classList.remove("hidden");
  }

  function closeDetail() {
    // Leaving the keyboard down on the way back shows the full result list.
    detailToken += 1;
    detailCardId = null;
    detailPane.classList.add("hidden");
    searchPane.classList.remove("hidden");
  }

  searchInput.addEventListener("input", scheduleSearch);
  searchInput.addEventListener("click", () => setKeyboardOpen(true));
  clearButton.addEventListener("click", () => {
    searchInput.value = "";
    scheduleSearch();
    setKeyboardOpen(true);
  });
  keyboardButton.addEventListener("click", () => setKeyboardOpen(!keyboardOpen));
  lookupBackButton.addEventListener("click", () => showView("menu"));
  detailBackButton.addEventListener("click", closeDetail);
  detailPrintButton.addEventListener("click", () => {
    const cardId = detailCardId;
    printCard(cardId, detailStatus, detailPrintButton, () => detailCardId !== cardId);
  });

  // ------------------------------------------------------------ entry points

  function onRandomCardShown() {
    rollCard();
  }

  async function onCardLookupShown() {
    const token = ++lookupShowToken;
    searchToken += 1;
    detailToken += 1;
    detailCardId = null;
    if (searchTimer !== null) {
      clearTimeout(searchTimer);
      searchTimer = null;
    }
    searchInput.value = "";
    detailPane.classList.add("hidden");
    lookupNotice.hide();
    searchPane.classList.remove("hidden");
    showHint("Type a card name to search.");

    // Nothing else on this screen would explain an unusable database - there
    // is no first result to fail - so it gets checked before the keyboard.
    const status = await fetchCardsStatus();
    if (lookupShowToken !== token) return;
    const description = describeStatus(status, "look cards up");
    if (description) {
      showLookupNotice(description);
      return;
    }
    setKeyboardOpen(true);
  }

  window.onRandomCardShown = onRandomCardShown;
  window.onCardLookupShown = onCardLookupShown;
})();
