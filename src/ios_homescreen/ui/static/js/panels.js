// The two side panels: the App Library on the left, the changes and Apply on the right.

import { useRef } from "preact/hooks";
import * as actions from "./actions.js";
import { startPress } from "./drag.js";
import { html } from "./html.js";
import { ICON } from "./layout.js";
import { describeChange, issueText, plural, refusalShort, relativeTime } from "./messages.js";
import { allItems, fromView, shownApps } from "./ops.js";
import { getState, setState, useStore } from "./store.js";
import { Icon, ItemIcon } from "./visuals.js";

const HOME_TYPES = new Set(["User", "System", ""]);

function libraryApps(state) {
  if (!state.draft) return [];
  const shown = shownApps(state.draft);
  const before = state.baseline ? shownApps(fromView(state.baseline)) : new Set();
  return state.apps
    .filter((app) => HOME_TYPES.has(app.type) && !shown.has(app.id))
    .map((app) => ({ ...app, leaving: before.has(app.id) }));
}

function LibraryRow({ app }) {
  const icon = useRef(null);
  const item = { type: "app", id: app.id, name: app.name, cells: 1, offloaded: false };
  const page = getState().page + 1;
  return html`<li
    class="lib-row"
    onPointerDown=${(event) => {
      if (event.target.closest("button")) return;
      startPress(event, { item, from: null, fromLibrary: true, el: icon.current, w: ICON, h: ICON });
    }}
  >
    <div class="lib-icon" ref=${icon}><${Icon} id=${app.id} name=${app.name} /></div>
    <div class="lib-text">
      <span class="lib-name">${app.name}</span>
      ${app.leaving ? html`<span class="lib-note">Moves here on Apply</span>` : null}
    </div>
    <button class="lib-add" title=${`Add to page ${page}`} aria-label=${`Add ${app.name} to page ${page}`} onClick=${() => actions.addFromLibrary(app)}>
      <svg viewBox="0 0 16 16"><path d="M8 3v10M3 8h10" /></svg>
    </button>
    <span class="grip" aria-hidden="true">
      <svg viewBox="0 0 10 16"><circle cx="3" cy="3" r="1.3" /><circle cx="7" cy="3" r="1.3" /><circle cx="3" cy="8" r="1.3" /><circle cx="7" cy="8" r="1.3" /><circle cx="3" cy="13" r="1.3" /><circle cx="7" cy="13" r="1.3" /></svg>
    </span>
  </li>`;
}

export function LibraryPanel() {
  const state = useStore();
  const apps = libraryApps(state);
  const query = state.search.trim().toLocaleLowerCase();
  const shown = query
    ? apps.filter((app) => app.name.toLocaleLowerCase().includes(query) || app.id.toLowerCase().includes(query))
    : apps;
  const drag = state.drag;
  const target = drag?.target;
  const dropping = drag && !drag.fromLibrary;
  const over = target?.zone === "library";
  return html`<aside
    class=${`panel library${state.drawer === "library" ? " is-open" : ""}${dropping ? " is-drop" : ""}${over ? " is-over" : ""}${over && target.invalid ? " is-refused" : ""}`}
    data-zone="library"
    aria-label="App Library"
  >
    <header class="panel-head">
      <h2>App Library</h2>
    </header>
    <p class="panel-hint">
      ${state.draft
        ? `${apps.length === 1 ? "1 installed app is" : `${apps.length} installed apps are`} not on the home screen. Drag one onto the phone.`
        : "Installed apps that are not on the home screen show up here."}
    </p>
    <label class="search">
      <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="5.5" /><path d="m13.2 13.2 3.8 3.8" /></svg>
      <input
        type="search"
        placeholder="Search apps"
        value=${state.search}
        onInput=${(e) => setState({ search: e.currentTarget.value })}
        aria-label="Search the App Library"
      />
    </label>
    <ul class="lib-list">
      ${shown.map((app) => html`<${LibraryRow} key=${app.id} app=${app} />`)}
    </ul>
    ${state.draft && !shown.length
      ? html`<div class="empty">${query ? `No app matches “${state.search}”.` : "Every installed app is on the home screen."}</div>`
      : null}
    <div class="drop-hint" aria-hidden="true">
      <svg viewBox="0 0 24 24"><path d="M4 7h16M6 7l1 12h10l1-12M9 7V4h6v3" /></svg>
      <span>${over && target.invalid ? refusalShort(target.invalid) : "Drop to move it to the App Library"}</span>
    </div>
  </aside>`;
}

function StatusLine() {
  const state = getState();
  const server = state.server || {};
  const job = state.job?.state === "running" ? state.job : null;
  const connection = server.connection?.kind === "wifi" ? "over Wi-Fi" : "over USB";
  let tone = "ok";
  let text = server.read?.at ? `Connected ${connection}, read ${relativeTime(server.read.at)}.` : `Connected ${connection}.`;
  if (server.demo) {
    tone = "demo";
    text = "Pretend phone. Nothing is sent to a real iPhone.";
  }
  if (job) {
    tone = "busy";
    text = job.events[job.events.length - 1]?.message || "Connecting...";
  } else if (server.error && !server.demo) {
    tone = "error";
    text = `Not connected: ${server.error.title}.`;
  } else if (!server.read && !server.demo) {
    tone = "idle";
    text = "Not read yet.";
  }
  return html`<p class=${`status-line tone-${tone}`} role="status">
    <span class="status-dot" aria-hidden="true"></span>${text}
  </p>`;
}

function ChangeIcon({ change }) {
  const state = getState();
  if (change.kind === "pages") {
    return html`<div class="change-glyph"><svg viewBox="0 0 20 20"><rect x="4" y="3" width="12" height="14" rx="2" /></svg></div>`;
  }
  const item =
    (state.draft && allItems(state.draft).find((x) => x.id === change.id)) ||
    (state.baseline && allItems(fromView(state.baseline)).find((x) => x.id === change.id)) || {
      type: change.type,
      id: change.id,
      name: change.name,
      pages: [[]],
    };
  return html`<div class="change-icon"><${ItemIcon} item=${item} /></div>`;
}

function Change({ change }) {
  const state = getState();
  const text = describeChange(change, state.draft);
  const clickable = change.id && !["to_library", "removed", "folder_deleted"].includes(change.kind);
  return html`<li class=${`change tone-${text.tone}`}>
    <button class="change-btn" disabled=${!clickable} onClick=${() => actions.reveal(change.id)} title=${clickable ? "Show it on the phone" : undefined}>
      <${ChangeIcon} change=${change} />
      <span class="change-text">
        <span class="change-name">${text.title}</span>
        <span class="change-detail">${text.detail}</span>
      </span>
    </button>
  </li>`;
}

function Issues() {
  const state = getState();
  const issues = state.check.issues || [];
  if (!issues.length) return null;
  return html`<div class="issues" role="alert">
    <p class="issues-head">
      ${issues.length === 1 ? "One thing to fix before applying:" : `${issues.length} things to fix before applying:`}
    </p>
    <ul>
      ${issues.map((issue) => {
        const page = issue.location?.section === "page" ? issue.location.page - 1 : null;
        return html`<li>
          <button class="issue" disabled=${page == null} onClick=${() => page != null && actions.goToPage(page)}>
            ${issueText(issue, actions.nameOf)}
          </button>
        </li>`;
      })}
    </ul>
  </div>`;
}

function summaryText(changes) {
  const count = (kinds) => changes.filter((c) => kinds.includes(c.kind)).length;
  const parts = [];
  const moved = count(["moved", "reordered"]);
  if (moved) parts.push(`${moved} moved`);
  const added = count(["added", "folder_created"]);
  if (added) parts.push(`${added} added`);
  const library = count(["to_library"]);
  if (library) parts.push(`${library} to the App Library`);
  const removed = count(["removed"]);
  if (removed) parts.push(`${removed} removed`);
  if (!parts.length) return "";
  const text = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0];
  return text[0].toUpperCase() + text.slice(1) + ".";
}

export function ChangesPanel() {
  const state = useStore();
  const check = state.check;
  const changes = check.changes || [];
  const running = state.job?.state === "running";
  const ready = state.draft && check.ok && check.dirty && !check.pending && !running;
  let label = "Apply";
  if (!state.draft) label = "Apply";
  else if (running) label = state.job.kind === "read" ? "Reading..." : "Applying...";
  else if (!check.ok) label = `Fix ${plural(check.issues.length, "problem")} to apply`;
  else if (!check.dirty) label = "No changes to apply";
  return html`<aside class=${`panel changes${state.drawer === "changes" ? " is-open" : ""}`} aria-label="Changes">
    <header class="panel-head">
      <h2>Changes</h2>
      <div class="head-actions">
        <button class="icon-btn" title="Undo (Ctrl+Z)" aria-label="Undo" disabled=${!state.past.length} onClick=${actions.undo}>
          <svg viewBox="0 0 20 20"><path d="M7.5 5 3.5 9l4 4" /><path d="M4 9h8a4.5 4.5 0 0 1 0 9h-2" /></svg>
        </button>
        <button class="icon-btn" title="Redo (Ctrl+Shift+Z)" aria-label="Redo" disabled=${!state.future.length} onClick=${actions.redo}>
          <svg viewBox="0 0 20 20"><path d="m12.5 5 4 4-4 4" /><path d="M16 9H8a4.5 4.5 0 0 0 0 9h2" /></svg>
        </button>
      </div>
    </header>
    <${StatusLine} />
    <${Issues} />
    ${changes.length
      ? html`<ul class="change-list">${changes.map((change, i) => html`<${Change} key=${`${change.kind}-${change.id || i}`} change=${change} />`)}</ul>`
      : html`<div class="changes-empty">
          <p><strong>No changes yet.</strong></p>
          <p>Drag icons on the phone. Each change is listed here before anything is written to it.</p>
        </div>`}
    <footer class="apply-bar">
      ${changes.length ? html`<div class="summary">${summaryText(changes)}</div>` : null}
      <button class="btn btn-apply" disabled=${!ready} onClick=${actions.openApply}>
        ${running ? html`<span class="spinner small"></span>` : null}${label}
      </button>
      <div class="apply-note">
        ${ready ? "A backup is saved first. If the phone does not match afterwards, the backup is written back." : ""}
        ${state.past.length && changes.length
          ? html`<button class="link-btn" onClick=${actions.discardChanges}>Discard changes</button>`
          : null}
      </div>
    </footer>
  </aside>`;
}
