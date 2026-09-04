const KEYBOARD_ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["shift", "z", "x", "c", "v", "b", "n", "m", "backspace"],
  ["space"],
];

let keyboardTarget = null;
let keyboardShift = false;

function buildKeyboard() {
  const container = document.getElementById("onscreen-keyboard");
  container.innerHTML = "";
  KEYBOARD_ROWS.forEach((row) => {
    const rowEl = document.createElement("div");
    rowEl.className = "keyboard-row";
    row.forEach((key) => {
      const keyEl = document.createElement("button");
      keyEl.type = "button";
      keyEl.className = "keyboard-key";
      if (key === "space") {
        keyEl.classList.add("keyboard-key-space");
        keyEl.textContent = " ";
      } else if (key === "backspace") {
        keyEl.classList.add("keyboard-key-wide");
        keyEl.textContent = "⌫";
      } else if (key === "shift") {
        keyEl.classList.add("keyboard-key-wide");
        keyEl.textContent = "⇧";
      } else {
        keyEl.textContent = key;
      }
      keyEl.addEventListener("click", () => handleKeyboardKey(key));
      rowEl.appendChild(keyEl);
    });
    container.appendChild(rowEl);
  });
}

function handleKeyboardKey(key) {
  if (!keyboardTarget) return;
  if (key === "shift") {
    keyboardShift = !keyboardShift;
    return;
  }
  if (key === "backspace") {
    keyboardTarget.value = keyboardTarget.value.slice(0, -1);
  } else if (key === "space") {
    keyboardTarget.value += " ";
  } else {
    keyboardTarget.value += keyboardShift ? key.toUpperCase() : key;
    keyboardShift = false;
  }
  keyboardTarget.dispatchEvent(new Event("input"));
}

function showKeyboardFor(inputEl) {
  keyboardTarget = inputEl;
  document.getElementById("onscreen-keyboard").classList.remove("hidden");
}

function hideKeyboard() {
  keyboardTarget = null;
  document.getElementById("onscreen-keyboard").classList.add("hidden");
}

buildKeyboard();
