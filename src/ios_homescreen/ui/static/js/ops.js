// Pure edits on a draft layout: { dock: [item], pages: [[item]] }.
// A folder is { type: "folder", id, name, pages: [[item]] }. Every function returns a
// new draft and leaves its input alone.
//
// A place ("container") is { s: "dock" } | { s: "page", p } | { s: "folder", fid, fp }.

import { DOCK_SLOTS, FOLDER_SLOTS, PAGE_CELLS, cells, pageCells } from "./layout.js";

export const FOLDABLE = new Set(["app", "webclip", "webapp"]);
// Widgets can be removed, after a confirmation; they cannot be put back from here.
export const REMOVABLE = new Set(["widget"]);
// A write cannot remove web clips or web apps: the iPhone puts them back.
export const STUCK = new Set(["webclip", "webapp"]);

let folderCounter = 0;
export function newFolderId() {
  folderCounter += 1;
  return `new-folder-${Date.now().toString(36)}-${folderCounter}`;
}

export function fromView(view) {
  return {
    dock: [...(view.dock || [])],
    pages: (view.pages || []).map((page) => [...(Array.isArray(page) ? page : page.items || [])]),
  };
}

export function toLayout(draft) {
  return { dock: draft.dock, pages: draft.pages.map((items) => ({ items })) };
}

function topLevel(draft) {
  return [
    ...draft.dock.map((item, i) => ({ item, s: "dock", i })),
    ...draft.pages.flatMap((page, p) => page.map((item, i) => ({ item, s: "page", p, i }))),
  ];
}

export function findFolder(draft, fid) {
  return topLevel(draft).find((entry) => entry.item.type === "folder" && entry.item.id === fid);
}

export function getList(draft, c) {
  if (c.s === "dock") return draft.dock;
  if (c.s === "page") return draft.pages[c.p] || [];
  const found = findFolder(draft, c.fid);
  return found ? found.item.pages[c.fp] || [] : [];
}

function replaceTop(draft, entry, item) {
  if (entry.s === "dock") {
    const dock = [...draft.dock];
    dock[entry.i] = item;
    return { ...draft, dock };
  }
  const pages = [...draft.pages];
  pages[entry.p] = [...pages[entry.p]];
  pages[entry.p][entry.i] = item;
  return { ...draft, pages };
}

export function setList(draft, c, list) {
  if (c.s === "dock") return { ...draft, dock: list };
  if (c.s === "page") {
    const pages = [...draft.pages];
    while (pages.length <= c.p) pages.push([]);
    pages[c.p] = list;
    return { ...draft, pages };
  }
  const found = findFolder(draft, c.fid);
  if (!found) return draft;
  const folderPages = [...found.item.pages];
  while (folderPages.length <= c.fp) folderPages.push([]);
  folderPages[c.fp] = list;
  return replaceTop(draft, found, { ...found.item, pages: folderPages });
}

// Where an item is: { c, i, item } or null.
export function locate(draft, id) {
  for (const entry of topLevel(draft)) {
    const c = entry.s === "dock" ? { s: "dock" } : { s: "page", p: entry.p };
    if (entry.item.id === id) return { c, i: entry.i, item: entry.item };
    if (entry.item.type === "folder") {
      for (let fp = 0; fp < entry.item.pages.length; fp++) {
        const i = entry.item.pages[fp].findIndex((x) => x.id === id);
        if (i >= 0) {
          return { c: { s: "folder", fid: entry.item.id, fp }, i, item: entry.item.pages[fp][i] };
        }
      }
    }
  }
  return null;
}

export function removeId(draft, id) {
  const where = locate(draft, id);
  if (!where) return { draft, item: null, from: null };
  const list = getList(draft, where.c).filter((x) => x.id !== id);
  return { draft: setList(draft, where.c, list), item: where.item, from: where };
}

export function insert(draft, c, index, item) {
  const list = [...getList(draft, c)];
  list.splice(Math.max(0, Math.min(index, list.length)), 0, item);
  return setList(draft, c, list);
}

// Folders: no empty pages, at most 9 items a page (the rest flows on), no empty folders.
export function tidyFolders(draft, keep = null) {
  const tidy = (item) => {
    if (item.type !== "folder") return item;
    const flowed = [];
    let carry = [];
    for (const page of item.pages) {
      const all = [...carry, ...page];
      carry = all.slice(FOLDER_SLOTS);
      flowed.push(all.slice(0, FOLDER_SLOTS));
    }
    while (carry.length) {
      flowed.push(carry.slice(0, FOLDER_SLOTS));
      carry = carry.slice(FOLDER_SLOTS);
    }
    const pages = flowed.filter((page) => page.length);
    if (!pages.length && item.id !== keep) return null;
    return { ...item, pages: pages.length ? pages : [[]] };
  };
  const clean = (list) => list.map(tidy).filter(Boolean);
  return { dock: clean(draft.dock), pages: draft.pages.map(clean) };
}

export function canMerge(item, target) {
  if (!item || !target || item.id === target.id || item.ghost || target.ghost) return false;
  return FOLDABLE.has(item.type) && (FOLDABLE.has(target.type) || target.type === "folder");
}

// Drop `item` (already taken out of `draft`) onto `targetId`: into its folder, or a new
// folder in the target's place.
export function mergeInto(draft, targetId, item, name = "New Folder") {
  const where = locate(draft, targetId);
  if (!where) return { draft, folderId: null };
  const target = where.item;
  if (target.type === "folder") {
    const last = target.pages.length - 1;
    const pages = target.pages.map((page) => [...page]);
    if (pages[last].length >= FOLDER_SLOTS) pages.push([item]);
    else pages[last].push(item);
    const list = [...getList(draft, where.c)];
    list[where.i] = { ...target, pages };
    return { draft: setList(draft, where.c, list), folderId: target.id };
  }
  const folder = { type: "folder", id: newFolderId(), name, cells: 1, pages: [[target, item]] };
  const list = [...getList(draft, where.c)];
  list[where.i] = folder;
  return { draft: setList(draft, where.c, list), folderId: folder.id };
}

export function renameFolder(draft, fid, name) {
  const found = findFolder(draft, fid);
  if (!found) return draft;
  return replaceTop(draft, found, { ...found.item, name });
}

// Put a folder's items where the folder was. Returns null if they do not fit.
export function ungroup(draft, fid) {
  const found = findFolder(draft, fid);
  if (!found) return null;
  const inner = found.item.pages.flat();
  if (found.s === "dock") {
    if (draft.dock.length - 1 + inner.length > DOCK_SLOTS) return null;
    const dock = [...draft.dock];
    dock.splice(found.i, 1, ...inner);
    return { ...draft, dock };
  }
  const page = draft.pages[found.p];
  if (pageCells(page) - 1 + inner.length > PAGE_CELLS) return null;
  const pages = [...draft.pages];
  pages[found.p] = [...page.slice(0, found.i), ...inner, ...page.slice(found.i + 1)];
  return { ...draft, pages };
}

export function addPage(draft, at) {
  const pages = [...draft.pages];
  pages.splice(at, 0, []);
  return { ...draft, pages };
}

export function removePage(draft, p) {
  if (draft.pages[p]?.length) return draft;
  return { ...draft, pages: draft.pages.filter((_, i) => i !== p) };
}

// Why `item` cannot go into `c` of `draft` (without the item), or null if it can.
export function blockReason(draft, item, c) {
  if (c.s === "dock") {
    if (item.type === "widget") return { code: "widget_in_dock" };
    if (draft.dock.length >= DOCK_SLOTS) {
      return { code: "dock_full", refused: true, details: { count: draft.dock.length + 1, capacity: DOCK_SLOTS } };
    }
    return null;
  }
  if (c.s === "folder") {
    if (item.type === "widget") return { code: "widget_in_folder" };
    if (item.type === "folder") return { code: "nested_folder" };
    return null;
  }
  const used = pageCells(draft.pages[c.p] || []);
  if (used + cells(item) > PAGE_CELLS) {
    return {
      code: "page_full",
      refused: true,
      location: { page: c.p + 1 },
      details: { cells: used + cells(item), capacity: PAGE_CELLS },
    };
  }
  return null;
}

// Ids of apps that are on the home screen (folders included).
export function shownApps(draft) {
  const ids = new Set();
  const visit = (item) => {
    if (item.type === "folder") item.pages.flat().forEach(visit);
    else if (item.type === "app") ids.add(item.id);
  };
  draft.dock.forEach(visit);
  draft.pages.flat().forEach(visit);
  return ids;
}

// Everything that is not a folder, folders included, flattened.
export function allItems(draft) {
  const found = [];
  const visit = (item) => {
    found.push(item);
    if (item.type === "folder") item.pages.flat().forEach(visit);
  };
  draft.dock.forEach(visit);
  draft.pages.flat().forEach(visit);
  return found;
}
