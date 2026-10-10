// Geometry of the phone screen, in logical points (an iPhone screen is 390 x 844),
// and how items flow into the 4 x 6 grid. Everything here is pure.

export const SCREEN_W = 390;
export const SCREEN_H = 844;
export const COLS = 4;
export const ROWS = 6;
export const ICON = 62;
export const PITCH_X = 87.5;
export const PITCH_Y = 96;
export const GRID_LEFT = (SCREEN_W - ((COLS - 1) * PITCH_X + ICON)) / 2;
export const GRID_TOP = 78;
export const DOCK_TOP = 726;
export const DOCK_HEIGHT = 94;
export const DOCK_ICON_TOP = DOCK_TOP + (DOCK_HEIGHT - ICON) / 2;
export const DOCK_SLOTS = 4;
export const PAGE_CELLS = 24;

export const FOLDER_COLS = 3;
export const FOLDER_ROWS = 3;
export const FOLDER_SLOTS = FOLDER_COLS * FOLDER_ROWS;
export const FOLDER_W = 304;
export const FOLDER_PITCH_X = 90;
export const FOLDER_PITCH_Y = 100;
export const FOLDER_PAD_X = (FOLDER_W - ((FOLDER_COLS - 1) * FOLDER_PITCH_X + ICON)) / 2;
export const FOLDER_PAD_Y = 26;
export const FOLDER_H = FOLDER_PAD_Y * 2 + (FOLDER_ROWS - 1) * FOLDER_PITCH_Y + ICON + 18;
export const FOLDER_LEFT = (SCREEN_W - FOLDER_W) / 2;
export const FOLDER_TOP = 236;

const WIDGET_SPAN = { small: [2, 2], medium: [4, 2], large: [4, 4], extraLarge: [4, 4] };
const WIDGET_CELLS = { small: 4, medium: 8, large: 16, extraLarge: 16 };

export function span(item) {
  if (item.type === "widget") return WIDGET_SPAN[item.size] || [2, 2];
  return [1, 1];
}

export function cells(item) {
  if (item.type === "widget") return WIDGET_CELLS[item.size] || 4;
  return 1;
}

export function pageCells(items) {
  return items.reduce((sum, item) => sum + cells(item), 0);
}

function fits(grid, row, col, w, h) {
  if (col + w > COLS) return false;
  for (let r = row; r < row + h; r++) {
    for (let c = col; c < col + w; c++) {
      if (grid[r]?.[c]) return false;
    }
  }
  return true;
}

function mark(grid, row, col, w, h, value) {
  for (let r = row; r < row + h; r++) {
    grid[r] = grid[r] || [];
    for (let c = col; c < col + w; c++) grid[r][c] = value;
  }
}

function place(items, dense) {
  // Like SpringBoard: items in order, left to right and top to bottom; widgets keep
  // to their halves (a small widget starts in column 1 or 3, wider ones in column 1).
  const grid = [];
  const placed = [];
  let cursor = 0;
  for (const item of items) {
    const [w, h] = span(item);
    let at = dense ? 0 : cursor;
    for (;;) {
      const row = Math.floor(at / COLS);
      const col = at % COLS;
      if (col % w === 0 && fits(grid, row, col, w, h)) {
        mark(grid, row, col, w, h, true);
        placed.push({ col, row, w, h });
        cursor = at + w;
        break;
      }
      at++;
    }
  }
  return placed;
}

// Grid positions ({col, row, w, h}) for the items of one page.
export function pack(items) {
  const sparse = place(items, false);
  const rows = Math.max(0, ...sparse.map((p) => p.row + p.h));
  if (rows <= ROWS) return sparse;
  const dense = place(items, true);
  return Math.max(0, ...dense.map((p) => p.row + p.h)) < rows ? dense : sparse;
}

export function cellBox(pos) {
  return {
    x: GRID_LEFT + pos.col * PITCH_X,
    y: GRID_TOP + pos.row * PITCH_Y,
    w: (pos.w - 1) * PITCH_X + ICON,
    h: (pos.h - 1) * PITCH_Y + ICON,
  };
}

// Dock icons are centred; four fill the same columns as the grid.
export function dockBoxes(count) {
  const gap = PITCH_X - ICON;
  const total = count * ICON + Math.max(0, count - 1) * gap;
  const left = (SCREEN_W - total) / 2;
  return Array.from({ length: count }, (_, i) => ({
    x: left + i * PITCH_X,
    y: DOCK_ICON_TOP,
    w: ICON,
    h: ICON,
  }));
}

export function folderBox(index) {
  const col = index % FOLDER_COLS;
  const row = Math.floor(index / FOLDER_COLS);
  return {
    x: FOLDER_PAD_X + col * FOLDER_PITCH_X,
    y: FOLDER_PAD_Y + row * FOLDER_PITCH_Y,
    w: ICON,
    h: ICON,
  };
}

// The insertion index that puts a dragged item (top-left at x, y) closest to where it
// is held. `others` are the page's items without the dragged one.
export function bestPageIndex(others, item, x, y, current) {
  const [w] = span(item);
  const targetCol = Math.max(0, Math.min(COLS - w, Math.round((x - GRID_LEFT) / PITCH_X)));
  const targetRow = Math.max(0, Math.round((y - GRID_TOP) / PITCH_Y));
  let best = null;
  for (let k = 0; k <= others.length; k++) {
    const list = [...others.slice(0, k), item, ...others.slice(k)];
    const pos = pack(list)[k];
    const score = Math.abs(pos.col - targetCol) + Math.abs(pos.row - targetRow) * 1.05;
    const better =
      !best || score < best.score - 1e-9 || (Math.abs(score - best.score) < 1e-9 && k === current);
    if (better) best = { k, score };
  }
  return best ? best.k : others.length;
}

export function bestDockIndex(count, x) {
  const boxes = dockBoxes(count + 1);
  let best = 0;
  let distance = Infinity;
  boxes.forEach((box, i) => {
    const d = Math.abs(box.x + box.w / 2 - x);
    if (d < distance) {
      distance = d;
      best = i;
    }
  });
  return best;
}

export function bestFolderIndex(count, x, y) {
  let best = 0;
  let distance = Infinity;
  for (let i = 0; i <= Math.min(count, FOLDER_SLOTS - 1); i++) {
    const box = folderBox(i);
    const d = Math.hypot(box.x - x, box.y - y);
    if (d < distance) {
      distance = d;
      best = i;
    }
  }
  return Math.min(best, count);
}

// Inside the middle of an icon: hovering there long enough makes a folder.
export function inCentre(box, x, y, inset = 15) {
  const size = Math.min(box.w, box.h, ICON);
  return (
    x >= box.x + inset && x <= box.x + size - inset && y >= box.y + inset && y <= box.y + size - inset
  );
}

// "Row 5, Col 2" for an item on a page, 1-based.
export function rowCol(items, id) {
  const index = items.findIndex((item) => item.id === id);
  if (index < 0) return null;
  const pos = pack(items)[index];
  return { row: pos.row + 1, col: pos.col + 1 };
}
