// Everything the UI does: edits with undo/redo, validation, and the device jobs.

import { ApiError, followJob, get, post } from "./api.js";
import { configureDrag } from "./drag.js";
import { PAGE_CELLS, pageCells } from "./layout.js";
import { refusalText } from "./messages.js";
import * as ops from "./ops.js";
import { getState, initState, setState } from "./store.js";

const HISTORY_LIMIT = 200;

initState({
  boot: "loading",
  server: null,
  baseline: null,
  apps: [],
  draft: null,
  removed: [],
  past: [],
  future: [],
  page: 0,
  openFolder: null,
  drag: null,
  dragPages: null,
  check: { ok: true, issues: [], changes: [], summary: null, dirty: false, pending: false },
  job: null,
  dialog: null,
  menu: null,
  toasts: [],
  search: "",
  icons: { available: new Set(), pending: false },
  wallpaper: null,
  flash: null,
  drawer: null,
});

// ------------------------------------------------------------------ helpers

export function nameOf(id) {
  const state = getState();
  const found = state.draft && ops.allItems(state.draft).find((item) => item.id === id);
  if (found) return found.name;
  const inBaseline = state.baseline && ops.allItems(ops.fromView(state.baseline)).find((x) => x.id === id);
  if (inBaseline) return inBaseline.name;
  return state.apps.find((app) => app.id === id)?.name || id;
}

let toastId = 0;
export function toast(text, options = {}) {
  toastId += 1;
  const entry = { id: toastId, text, tone: options.tone || "info", action: options.action || null };
  setState((state) => ({ toasts: [...state.toasts.slice(-3), entry] }));
  setTimeout(() => dismissToast(entry.id), options.duration || 5000);
}

export function dismissToast(id) {
  setState((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
}

function explain(problem) {
  return refusalText(problem, nameOf);
}

function stuckHint(item) {
  showProblem({ code: "not_removable", details: { id: item.id, kind: item.type, name: item.name } });
}

function clampPage(page, draft) {
  return Math.max(0, Math.min(page, Math.max(0, draft.pages.length - 1)));
}

// ------------------------------------------------------------------ history

export function commit(draft, { removed, label } = {}) {
  const state = getState();
  const tidy = ops.tidyFolders(draft);
  const past = [...state.past, { draft: state.draft, removed: state.removed, page: state.page }].slice(-HISTORY_LIMIT);
  let openFolder = state.openFolder;
  if (openFolder && !ops.findFolder(tidy, openFolder.id)) openFolder = null;
  setState({
    draft: tidy,
    removed: removed ?? state.removed,
    past,
    future: [],
    openFolder,
    page: clampPage(state.page, tidy),
    menu: null,
  });
  scheduleCheck();
  if (label) toast(label, { action: { label: "Undo", run: undo } });
}

export function undo() {
  const state = getState();
  const last = state.past[state.past.length - 1];
  if (!last || state.drag) return;
  setState({
    draft: last.draft,
    removed: last.removed,
    page: clampPage(last.page, last.draft),
    past: state.past.slice(0, -1),
    future: [{ draft: state.draft, removed: state.removed, page: state.page }, ...state.future],
    openFolder: null,
    menu: null,
  });
  scheduleCheck();
}

export function redo() {
  const state = getState();
  const next = state.future[0];
  if (!next || state.drag) return;
  setState({
    draft: next.draft,
    removed: next.removed,
    page: clampPage(next.page, next.draft),
    past: [...state.past, { draft: state.draft, removed: state.removed, page: state.page }],
    future: state.future.slice(1),
    openFolder: null,
    menu: null,
  });
  scheduleCheck();
}

export function discardChanges() {
  const state = getState();
  if (!state.baseline) return;
  commit(ops.fromView(state.baseline), { removed: [], label: "Changes discarded." });
  setState({ page: 0, dialog: null });
}

// ------------------------------------------------------------------ validation

let checkTimer = null;
let checkSeq = 0;

export function scheduleCheck() {
  clearTimeout(checkTimer);
  setState((state) => ({ check: { ...state.check, pending: true } }));
  checkTimer = setTimeout(runCheck, 120);
}

async function runCheck() {
  const state = getState();
  if (!state.draft) return;
  checkSeq += 1;
  const seq = checkSeq;
  try {
    const result = await post("/api/plan", { layout: ops.toLayout(state.draft), remove: state.removed });
    if (seq === checkSeq) setState({ check: { ...result, pending: false } });
  } catch (error) {
    if (seq === checkSeq) {
      setState((s) => ({ check: { ...s.check, pending: false } }));
      if (error.code !== "no_read") toast(error.message, { tone: "error" });
    }
  }
}

// ------------------------------------------------------------------ server state

function adopt(server, { reset }) {
  const state = getState();
  const view = server.read?.view || null;
  const patch = { server, baseline: view, apps: server.read?.apps || [], boot: "ready" };
  if (view && (reset || !state.draft)) {
    // Showcase mode can start from another layout than the one changes are counted from.
    const draft = ops.fromView(server.read.draft || view);
    Object.assign(patch, {
      draft,
      removed: [],
      past: [],
      future: [],
      page: clampPage(state.page, draft),
      openFolder: null,
    });
  }
  setState(patch);
  if (view) scheduleCheck();
  if (server.icons) adoptIcons(server.icons);
}

function adoptIcons(icons) {
  setState({
    icons: { available: new Set(icons.available), pending: icons.pending },
    wallpaper: icons.wallpaper || null,
  });
  if (icons.pending) setTimeout(pollIcons, 1000);
}

let polling = false;
async function pollIcons() {
  if (polling) return;
  polling = true;
  try {
    adoptIcons(await get("/api/icons"));
  } catch {
    // the next read or reload tries again
  } finally {
    polling = false;
  }
}

export async function boot() {
  try {
    const server = await get("/api/state");
    adopt(server, { reset: true });
    if (server.job && server.job.state === "running") await follow(server.job);
  } catch (error) {
    setState({ boot: "ready", server: { error: { title: "Cannot reach the server", steps: [], detail: error.message } } });
  }
}

async function reload(reset) {
  adopt(await get("/api/state"), { reset });
}

// ------------------------------------------------------------------ jobs

async function follow(job) {
  setState({ job });
  const finished = await followJob(job.event_count ?? job.events.length, (event) =>
    setState((state) => ({ job: state.job && { ...state.job, events: [...state.job.events, event] } })),
  );
  if (finished) setState((state) => ({ job: { ...finished, events: state.job?.events || finished.events } }));
  return finished;
}

function isDirty() {
  const state = getState();
  return state.check.dirty || state.removed.length > 0;
}

export function readFromPhone({ confirmed = false } = {}) {
  if (!confirmed && isDirty()) {
    setState({ dialog: { kind: "confirm-read" } });
    return;
  }
  setState({ dialog: null });
  runRead();
}

async function runRead() {
  let job;
  try {
    ({ job } = await post("/api/read"));
  } catch (error) {
    toast(error.message, { tone: "error" });
    return;
  }
  const hadRead = Boolean(getState().baseline);
  const finished = await follow(job);
  if (finished?.state === "done") {
    await reload(true);
    toast("Read the home screen from the phone.", { tone: "success" });
  } else {
    await reload(false);
    if (hadRead && finished?.error) setState({ dialog: { kind: "error", error: finished.error } });
  }
}

export function openApply() {
  const state = getState();
  if (!state.check.ok || !state.check.dirty || state.check.pending) return;
  if (state.server?.showcase) {
    setState({ dialog: { kind: "showcase" }, drawer: null });
    return;
  }
  setState({ dialog: { kind: "apply" }, drawer: null });
}

export async function startApply({ force = false } = {}) {
  const state = getState();
  let job;
  try {
    ({ job } = await post("/api/apply", { layout: ops.toLayout(state.draft), remove: state.removed, force }));
  } catch (error) {
    if (error instanceof ApiError && error.data.issues) {
      setState({ check: { ...state.check, ok: false, issues: error.data.issues }, dialog: null });
      toast("The layout has problems; see Changes.", { tone: "error" });
    } else {
      toast(error.message, { tone: "error" });
    }
    return;
  }
  setState({ dialog: { kind: "job", jobKind: "apply" } });
  const finished = await follow(job);
  const status = finished?.result?.status;
  // After "applied" the phone matches the draft: start fresh from the new read.
  await reload(status === "applied");
}

export async function restoreBackup(name) {
  let job;
  try {
    ({ job } = await post("/api/backups/restore", { name }));
  } catch (error) {
    toast(error.message, { tone: "error" });
    return;
  }
  setState({ dialog: { kind: "job", jobKind: "restore", backup: name } });
  const finished = await follow(job);
  await reload(finished?.state === "done");
}

export async function openBackups() {
  setState({ dialog: { kind: "backups", backups: null } });
  try {
    const { backups } = await get("/api/backups");
    setState((state) => (state.dialog?.kind === "backups" ? { dialog: { ...state.dialog, backups } } : null));
  } catch (error) {
    toast(error.message, { tone: "error" });
  }
}

// ------------------------------------------------------------------ files

export async function exportLayout() {
  const state = getState();
  if (!state.draft) return;
  try {
    const { toml } = await post("/api/export", { layout: ops.toLayout(state.draft), remove: state.removed });
    const url = URL.createObjectURL(new Blob([toml], { type: "application/toml" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "layout.toml";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Saved layout.toml.", { tone: "success" });
  } catch (error) {
    if (error.data?.issues) toast("Fix the problems listed under Changes before exporting.", { tone: "error" });
    else toast(error.message, { tone: "error" });
  }
}

export async function importLayout(file) {
  let text;
  try {
    text = await file.text();
  } catch {
    toast("Could not read that file.", { tone: "error" });
    return;
  }
  try {
    const result = await post("/api/import", { toml: text });
    if (result.removed.length) {
      setState({ dialog: { kind: "confirm-import", result, file: file.name } });
    } else {
      useImported(result);
    }
  } catch (error) {
    if (error.data?.issues) {
      setState({ dialog: { kind: "import-issues", issues: error.data.issues, file: file.name } });
    } else {
      toast(error.message, { tone: "error" });
    }
  }
}

export function useImported(result) {
  const state = getState();
  const removed = [...new Set([...state.removed, ...result.removed.map((x) => x.id)])];
  commit(ops.fromView(result.view), { removed, label: "Imported the layout file." });
  setState({ dialog: null, page: 0 });
}

// ------------------------------------------------------------------ edits

export function dropItem(source, target, base) {
  const { item } = source;
  if (target.zone === "library") {
    if (ops.STUCK.has(item.type)) return stuckHint(item);
    if (ops.REMOVABLE.has(item.type)) return askRemove(item, base);
    return commit(base, { label: `${item.name} goes to the App Library.` });
  }
  if (target.zone === "merge") {
    const target_ = ops.locate(base, target.targetId)?.item;
    const { draft, folderId } = ops.mergeInto(base, target.targetId, item);
    if (!folderId) return;
    commit(draft);
    if (target_ && target_.type !== "folder") {
      const where = ops.locate(getState().draft, folderId);
      if (where) setState({ openFolder: { id: folderId, page: 0, editing: true } });
    }
    return;
  }
  const draft = ops.insert(base, target.c, target.index, item);
  if (target.c.s === "page") setState({ page: target.c.p });
  commit(draft);
}

export function showProblem(problem) {
  toast(explain(problem), { tone: "warning" });
}

configureDrag({ drop: dropItem, message: showProblem });

export function askRemove(item, base = null) {
  setState({ dialog: { kind: "confirm-remove", item, base }, menu: null });
}

// Only widgets get here: they are the one kind a write can remove.
export function confirmRemove() {
  const state = getState();
  const { item, base } = state.dialog;
  const next = base || ops.removeId(state.draft, item.id).draft;
  setState({ dialog: null });
  commit(next, {
    removed: [...new Set([...state.removed, item.id])],
    label: `The ${item.name} widget will be removed.`,
  });
}

// The minus badge / Delete key / menu: apps go to the App Library, widgets ask first,
// web clips and web apps cannot go (the iPhone puts them back).
export function sendAway(item) {
  if (item.type === "folder") {
    const stuck = item.pages.flat().find((x) => ops.STUCK.has(x.type));
    if (stuck) {
      toast(`${item.name} holds ${stuck.name}, which can't be removed from here. Take it out of the folder first, or unpack the folder.`, { tone: "warning", duration: 7000 });
      return;
    }
    return commit(ops.removeId(getState().draft, item.id).draft, {
      label: `Folder ${item.name}: its apps go to the App Library.`,
    });
  }
  if (ops.STUCK.has(item.type)) return stuckHint(item);
  if (ops.REMOVABLE.has(item.type)) return askRemove(item);
  commit(ops.removeId(getState().draft, item.id).draft, { label: `${item.name} goes to the App Library.` });
}

export function addFromLibrary(app) {
  const state = getState();
  if (!state.draft) return;
  const page = state.draft.pages[state.page] || [];
  const item = { type: "app", id: app.id, name: app.name, cells: 1, offloaded: false };
  if (pageCells(page) + 1 > PAGE_CELLS) {
    return showProblem({ code: "page_full", refused: true, location: { page: state.page + 1 }, details: { cells: PAGE_CELLS + 1, capacity: PAGE_CELLS } });
  }
  commit(ops.insert(state.draft, { s: "page", p: state.page }, page.length, item));
  flash(app.id);
}

export function moveTo(item, c) {
  const state = getState();
  const base = ops.removeId(state.draft, item.id).draft;
  const reason = ops.blockReason(base, item, c);
  if (reason) return showProblem(reason);
  const list = ops.getList(base, c);
  commit(ops.insert(base, c, list.length, item));
  if (c.s === "page") setState({ page: c.p });
  flash(item.id);
}

export function intoNewFolder(item) {
  const state = getState();
  const where = ops.locate(state.draft, item.id);
  if (!where || where.c.s === "folder") return;
  const folder = { type: "folder", id: ops.newFolderId(), name: "New Folder", cells: 1, pages: [[item]] };
  const list = [...ops.getList(state.draft, where.c)];
  list[where.i] = folder;
  commit(ops.setList(state.draft, where.c, list));
  setState({ openFolder: { id: folder.id, page: 0, editing: true } });
}

export function openFolder(id, editing = false) {
  setState({ openFolder: { id, page: 0, editing }, menu: null });
}

export function closeFolder() {
  setState({ openFolder: null });
}

export function renameFolder(id, name) {
  const state = getState();
  const clean = name.trim();
  const found = ops.findFolder(state.draft, id);
  if (!found) return;
  if (!clean) {
    showProblem({ code: "folder_name_missing" });
    return;
  }
  if (clean !== found.item.name) commit(ops.renameFolder(state.draft, id, clean));
}

export function ungroupFolder(item) {
  const state = getState();
  const next = ops.ungroup(state.draft, item.id);
  if (!next) {
    toast(`There is no room to unpack ${item.name} here.`, { tone: "warning" });
    return;
  }
  commit(next, { label: `Unpacked the folder ${item.name}.` });
}

export function addPage() {
  const state = getState();
  const at = state.page + 1;
  commit(ops.addPage(state.draft, at));
  setState({ page: at });
}

export function removePage() {
  const state = getState();
  if (state.draft.pages[state.page]?.length || state.draft.pages.length <= 1) return;
  commit(ops.removePage(state.draft, state.page));
}

export function goToPage(page) {
  const state = getState();
  const count = state.draft ? state.draft.pages.length : 0;
  if (page < 0 || page >= count) return;
  setState({ page, openFolder: null, menu: null });
}

export function flash(id) {
  setState({ flash: { id, at: Date.now() } });
  setTimeout(() => setState((state) => (state.flash?.id === id ? { flash: null } : null)), 1600);
}

// Jump to where a change happened.
export function reveal(id) {
  const state = getState();
  const where = ops.locate(state.draft, id);
  if (!where) return;
  if (where.c.s === "page") setState({ page: where.c.p, openFolder: null });
  if (where.c.s === "folder") {
    const folder = ops.locate(state.draft, where.c.fid);
    if (folder?.c.s === "page") setState({ page: folder.c.p });
    setState({ openFolder: { id: where.c.fid, page: where.c.fp, editing: false } });
  }
  setState({ drawer: null });
  flash(id);
}
