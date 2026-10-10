// Pointer-based drag and drop for the phone, the dock, folders and the App Library.
//
// Drop zones are found with elementFromPoint and [data-zone] attributes:
//   screen  - the phone screen (pages, dock, open folder)
//   library - the App Library panel (send an item there)
//   flip    - page arrows and dots (hover to change page; data-flip="prev|next|N")
// The ghost follows the pointer outside of Preact; the store only changes when the
// drop target changes, and the phone renders the preview from it (preview.js).

import * as L from "./layout.js";
import { STUCK, blockReason, canMerge, getList } from "./ops.js";
import { refusalShort } from "./messages.js";
import { baseFor } from "./preview.js";
import { getState, setState } from "./store.js";

let hooks = { drop: () => {}, message: () => {} };
let drag = null;
let suppressClicksUntil = 0;
const timers = new Map();

export function configureDrag(callbacks) {
  hooks = { ...hooks, ...callbacks };
}

window.addEventListener(
  "click",
  (event) => {
    if (Date.now() < suppressClicksUntil) {
      event.stopPropagation();
      event.preventDefault();
    }
  },
  true,
);

window.addEventListener("keydown", (event) => {
  if (drag && event.key === "Escape") abort();
});

function timer(name, ms, fn) {
  if (timers.has(name)) return;
  timers.set(
    name,
    setTimeout(() => {
      timers.delete(name);
      if (drag) fn();
    }, ms),
  );
}

function cancelTimer(name) {
  clearTimeout(timers.get(name));
  timers.delete(name);
}

function cancelAll() {
  for (const id of timers.values()) clearTimeout(id);
  timers.clear();
}

// source: { item, from, fromLibrary, el (visual to copy), w, h (logical size) }
export function startPress(event, source) {
  if (event.button !== 0 || drag || getState().job?.state === "running") return;
  const { pointerId, clientX: startX, clientY: startY } = event;
  const move = (e) => {
    if (e.pointerId !== pointerId) return;
    if (!drag) {
      if (Math.hypot(e.clientX - startX, e.clientY - startY) < 6) return;
      begin(source, startX, startY);
    }
    drag.x = e.clientX;
    drag.y = e.clientY;
    drag.ghost.style.transform = `translate(${e.clientX - drag.offsetX}px, ${e.clientY - drag.offsetY}px)`;
    evaluate();
  };
  const stop = (e) => {
    if (e.pointerId !== pointerId) return;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
    if (!drag) return;
    if (e.type === "pointercancel") abort();
    else finish();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
}

function phoneScale() {
  const screen = document.querySelector('[data-zone="screen"]');
  if (!screen) return 1;
  return screen.getBoundingClientRect().width / L.SCREEN_W;
}

function begin(source, startX, startY) {
  const scale = phoneScale();
  const rect = source.el.getBoundingClientRect();
  const offsetX = source.fromLibrary ? (L.ICON * scale) / 2 : startX - rect.left;
  const offsetY = source.fromLibrary ? (L.ICON * scale) / 2 : startY - rect.top;
  const ghost = document.createElement("div");
  ghost.className = "drag-ghost";
  ghost.style.width = `${source.w * scale}px`;
  ghost.style.height = `${source.h * scale}px`;
  const inner = document.createElement("div");
  inner.className = "drag-ghost-inner";
  inner.style.width = `${source.w}px`;
  inner.style.height = `${source.h}px`;
  inner.style.transform = `scale(${scale})`;
  const copy = source.el.cloneNode(true);
  copy.removeAttribute("data-id");
  inner.appendChild(copy);
  ghost.appendChild(inner);
  const hint = document.createElement("div");
  hint.className = "drag-hint";
  hint.hidden = true;
  ghost.appendChild(hint);
  document.body.appendChild(ghost);
  document.body.classList.add("is-dragging");
  drag = {
    item: source.item,
    from: source.from,
    fromLibrary: Boolean(source.fromLibrary),
    offsetX,
    offsetY,
    ghost,
    hint,
    x: startX,
    y: startY,
    target: null,
    pending: null,
    mergeCandidate: null,
  };
  setState({
    drag: { item: source.item, from: source.from, fromLibrary: drag.fromLibrary, target: null },
    menu: null,
    drawer: null,
  });
}

function sameContainer(a, b) {
  if (!a || !b || a.s !== b.s) return false;
  if (a.s === "page") return a.p === b.p;
  if (a.s === "folder") return a.fid === b.fid && a.fp === b.fp;
  return true;
}

function sameTarget(a, b) {
  if (!a || !b) return a === b;
  return (
    a.zone === b.zone &&
    sameContainer(a.c, b.c) &&
    a.index === b.index &&
    a.targetId === b.targetId &&
    (a.invalid?.code || null) === (b.invalid?.code || null)
  );
}

function setTarget(target) {
  cancelTimer("reorder");
  drag.pending = null;
  if (sameTarget(target, drag.target)) return;
  drag.target = target;
  drag.hint.textContent = target?.invalid ? refusalShort(target.invalid) : "";
  drag.hint.hidden = !target?.invalid;
  setState((state) => ({ drag: state.drag && { ...state.drag, target } }));
}

// Reordering waits a moment so icons do not jump away while you aim for a folder:
// briefly over empty space, longer while the pointer is on another icon.
function propose(target, delay = 110) {
  if (sameTarget(target, drag.target)) {
    cancelTimer("reorder");
    drag.pending = null;
    return;
  }
  const fresh = !drag.target || drag.target.invalid || !sameContainer(drag.target.c, target.c);
  if (fresh) return setTarget(target);
  // A debounce: icons only make room once the pointer pauses.
  cancelTimer("reorder");
  drag.pending = target;
  timer("reorder", delay, () => drag.pending && setTarget(drag.pending));
}

function evaluate() {
  const element = document.elementFromPoint(drag.x, drag.y);
  const zone = element?.closest("[data-zone]");
  const kind = zone?.dataset.zone;
  if (kind !== "screen") {
    cancelTimer("edge");
    cancelTimer("exit");
  }
  if (kind !== "flip") cancelTimer("flip");
  if (kind === "screen") return overScreen(zone);
  if (kind === "library") return setTarget(libraryTarget());
  if (kind === "flip") {
    const flip = zone.dataset.flip;
    timer("flip", 450, () => {
      const page = getState().page;
      if (flip === "prev") flipTo(page - 1);
      else if (flip === "next") flipTo(page + 1);
      else flipTo(Number(flip));
    });
    return;
  }
  setTarget(null);
}

function libraryTarget() {
  const item = drag.item;
  if (drag.fromLibrary) return null;
  if (item.type === "folder") return { zone: "library", invalid: { code: "folder_to_library" } };
  if (STUCK.has(item.type)) {
    return {
      zone: "library",
      invalid: { code: "not_removable", details: { id: item.id, kind: item.type, name: item.name } },
    };
  }
  return { zone: "library" };
}

function pageCount(state) {
  const pages = state.draft.pages;
  const last = pages[pages.length - 1];
  // One extra page past the end while dragging, like SpringBoard.
  return last && last.length ? pages.length + 1 : pages.length;
}

function flipTo(page) {
  const state = getState();
  if (page < 0 || page >= pageCount(state) || page === state.page) return;
  setState({ page, dragPages: pageCount(state) });
  evaluate();
}

function overScreen(screen) {
  const rect = screen.getBoundingClientRect();
  const scale = rect.width / L.SCREEN_W;
  const px = (drag.x - rect.left) / scale;
  const py = (drag.y - rect.top) / scale;
  const gx = (drag.x - drag.offsetX - rect.left) / scale;
  const gy = (drag.y - drag.offsetY - rect.top) / scale;
  const state = getState();

  if (state.openFolder) {
    const inside =
      px >= L.FOLDER_LEFT - 12 &&
      px <= L.FOLDER_LEFT + L.FOLDER_W + 12 &&
      py >= L.FOLDER_TOP - 70 &&
      py <= L.FOLDER_TOP + L.FOLDER_H + 30;
    if (inside) {
      cancelTimer("exit");
      return folderTarget(state, gx - L.FOLDER_LEFT, gy - L.FOLDER_TOP, px - L.FOLDER_LEFT);
    }
    // Leaving the folder closes it after a moment, then the home screen takes over.
    timer("exit", 350, () => {
      setState({ openFolder: null });
      evaluate();
    });
    return;
  }
  if (py >= L.DOCK_TOP - 16) {
    cancelTimer("edge");
    return dockTarget(state, px, py);
  }
  if (px < 18 || px > L.SCREEN_W - 18) {
    const step = px < 18 ? -1 : 1;
    timer("edge", 600, () => flipTo(getState().page + step));
  } else {
    cancelTimer("edge");
  }
  return pageTarget(state, gx, gy, px, py);
}

// Returns the reorder delay to use, or null when the pointer rests on an icon's
// centre (hovering there makes a folder, or adds to one).
function mergeOrHold(shown, boxes, c, px, py, current) {
  const onIcon = (box) => px >= box.x && px <= box.x + box.w && py >= box.y && py <= box.y + box.h;
  const hit = shown.findIndex((item, i) => !item.ghost && onIcon(boxes[i]));
  if (hit >= 0 && canMerge(drag.item, shown[hit]) && L.inCentre(boxes[hit], px, py)) {
    const targetId = shown[hit].id;
    if (drag.target?.zone === "merge" && drag.target.targetId === targetId) return null;
    if (drag.mergeCandidate !== targetId) {
      cancelTimer("merge");
      drag.mergeCandidate = targetId;
    }
    cancelTimer("reorder");
    drag.pending = null;
    timer("merge", 450, () => setTarget({ zone: "merge", c, targetId, index: current }));
    return null;
  }
  cancelTimer("merge");
  drag.mergeCandidate = null;
  return hit >= 0 ? 380 : 110;
}

function currentIndex(c) {
  const t = drag.target;
  return t && !t.invalid && t.zone !== "merge" && sameContainer(t.c, c) ? t.index : null;
}

function pageTarget(state, gx, gy, px, py) {
  const base = baseFor(state);
  const c = { s: "page", p: state.page };
  const others = base.pages[state.page] || [];
  const current = currentIndex(c);
  const shown = current == null ? others : [...others.slice(0, current), { ...drag.item, ghost: true }, ...others.slice(current)];
  const positions = L.pack(shown);
  const delay = mergeOrHold(shown, positions.map(L.cellBox), c, px, py, current);
  if (delay === null) return;
  const reason = blockReason(base, drag.item, c);
  if (reason) return setTarget({ zone: "page", c, invalid: reason });
  const index = L.bestPageIndex(others, drag.item, gx, gy, current);
  propose({ zone: "page", c, index }, delay);
}

function dockTarget(state, px, py) {
  const base = baseFor(state);
  const c = { s: "dock" };
  const current = currentIndex(c);
  const shown = current == null ? base.dock : [...base.dock.slice(0, current), { ...drag.item, ghost: true }, ...base.dock.slice(current)];
  const delay = mergeOrHold(shown, L.dockBoxes(shown.length), c, px, py, current);
  if (delay === null) return;
  const reason = blockReason(base, drag.item, c);
  if (reason) return setTarget({ zone: "dock", c, invalid: reason });
  propose({ zone: "dock", c, index: L.bestDockIndex(base.dock.length, px) }, delay);
}

function folderTarget(state, gx, gy, px) {
  const folder = state.openFolder;
  const base = baseFor(state);
  const c = { s: "folder", fid: folder.id, fp: folder.page };
  const reason = blockReason(base, drag.item, c);
  if (reason) return setTarget({ zone: "folder", c, invalid: reason });
  if (px < 10 || px > L.FOLDER_W - 10) {
    const step = px < 10 ? -1 : 1;
    timer("edge", 600, () => {
      const open = getState().openFolder;
      const found = base.dock.concat(base.pages.flat()).find((x) => x.id === open?.id);
      const pages = found ? found.pages.length : 1;
      const next = open.page + step;
      if (next >= 0 && next < pages) {
        setState({ openFolder: { ...open, page: next } });
        evaluate();
      }
    });
  } else {
    cancelTimer("edge");
  }
  const others = getList(base, c);
  propose({ zone: "folder", c, index: L.bestFolderIndex(others.length, gx, gy) });
}

function teardown() {
  cancelAll();
  drag.ghost.remove();
  document.body.classList.remove("is-dragging");
  suppressClicksUntil = Date.now() + 80;
}

function finish() {
  const state = getState();
  const result = { item: drag.item, from: drag.from, fromLibrary: drag.fromLibrary };
  const target = drag.pending || drag.target;
  const base = baseFor(state);
  teardown();
  drag = null;
  setState({ drag: null, dragPages: null });
  if (!target) return;
  if (target.invalid) return hooks.message(target.invalid);
  hooks.drop(result, target, base);
}

function abort() {
  teardown();
  drag = null;
  setState({ drag: null, dragPages: null });
}
