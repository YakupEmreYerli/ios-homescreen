// The phone in the middle: pages, dock, open folder, page controls, and the states
// before a read (reading, or a friendly error).

import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import * as actions from "./actions.js";
import { wallpaperUrl } from "./api.js";
import { startPress } from "./drag.js";
import { html } from "./html.js";
import * as L from "./layout.js";
import { findFolder } from "./ops.js";
import { displayed } from "./preview.js";
import { getState, setState, useStore } from "./store.js";
import { Badge, Visual, widgetLabel } from "./visuals.js";

const BEZEL = 13;
const FRAME_W = L.SCREEN_W + BEZEL * 2;
const FRAME_H = L.SCREEN_H + BEZEL * 2;

function openMenu(event, item) {
  event.preventDefault();
  event.stopPropagation();
  setState({ menu: { x: event.clientX, y: event.clientY, item } });
}

function HomeItem({ item, box, where, inDock = false, merge = false }) {
  const state = getState();
  const tile = useRef(null);
  const flash = state.flash?.id === item.id;
  const style = { transform: `translate(${box.x}px, ${box.y}px)`, width: `${box.w}px`, height: `${box.h}px` };
  if (item.ghost) {
    return html`<div class=${`item is-ghost item-${item.type}`} style=${style} key=${item.id}>
      <div class="slot"></div>
    </div>`;
  }
  const press = (event) =>
    startPress(event, { item, from: where, el: tile.current, w: box.w, h: box.h });
  const click = () => {
    if (item.type === "folder") actions.openFolder(item.id);
  };
  const keydown = (event) => {
    if (event.key === "Enter" && item.type === "folder") actions.openFolder(item.id);
    if (event.key === "Delete" || event.key === "Backspace") actions.sendAway(item);
    if (event.key === "ContextMenu") {
      const rect = tile.current.getBoundingClientRect();
      setState({ menu: { x: rect.right, y: rect.top, item } });
    }
  };
  const label = item.type === "widget" ? widgetLabel(item) : item.name;
  const title = item.type === "widget" ? `${label} widget` : item.name;
  return html`<div
    class=${`item item-${item.type}${flash ? " is-flash" : ""}${merge ? " is-merge" : ""}${inDock ? " in-dock" : ""}`}
    style=${style}
    data-id=${item.id}
  >
    <div
      class="tile"
      ref=${tile}
      tabindex="0"
      role="button"
      aria-label=${title}
      title=${inDock ? title : undefined}
      onPointerDown=${press}
      onClick=${click}
      onKeyDown=${keydown}
      onContextMenu=${(e) => openMenu(e, item)}
    >
      <${Visual} item=${item} />
      <${Badge} item=${item} />
    </div>
    ${inDock ? null : html`<div class="label">${label}</div>`}
    <button
      class="minus"
      tabindex="-1"
      aria-label=${`Options for ${item.name}`}
      onPointerDown=${(e) => e.stopPropagation()}
      onClick=${(e) => openMenu(e, item)}
    >
      <svg viewBox="0 0 12 12"><path d="M3 6h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
    </button>
  </div>`;
}

function PageGrid({ items, page, highlight }) {
  const positions = L.pack(items);
  const rows = Math.max(L.ROWS, ...positions.map((p) => p.row + p.h));
  return html`<div class=${`page-grid${rows > L.ROWS ? " is-over" : ""}`}>
    ${items.map((item, i) => {
      const box = L.cellBox(positions[i]);
      return html`<${HomeItem}
        key=${item.id}
        item=${item}
        box=${box}
        where=${{ c: { s: "page", p: page }, i }}
        merge=${highlight === item.id}
      />`;
    })}
  </div>`;
}

function Dock({ items, highlight, blocked }) {
  const boxes = L.dockBoxes(items.length);
  return html`<div class=${`dock${blocked ? " is-blocked" : ""}`}>
    <div class="dock-glass"></div>
    ${items.map(
      (item, i) =>
        html`<${HomeItem}
          key=${item.id}
          item=${item}
          box=${boxes[i]}
          where=${{ c: { s: "dock" }, i }}
          inDock=${true}
          merge=${highlight === item.id}
        />`,
    )}
  </div>`;
}

function FolderTitle({ folder }) {
  const state = getState();
  const [value, setValue] = useState(folder.name);
  const input = useRef(null);
  useEffect(() => setValue(folder.name), [folder.name]);
  useEffect(() => {
    if (state.openFolder?.editing && input.current) {
      input.current.focus();
      input.current.select();
      setState({ openFolder: { ...state.openFolder, editing: false } });
    }
  }, [state.openFolder?.editing]);
  const save = () => {
    if (!value.trim()) {
      setValue(folder.name);
      actions.showProblem({ code: "folder_name_missing" });
      return;
    }
    actions.renameFolder(folder.id, value);
  };
  return html`<input
    ref=${input}
    class="folder-title"
    value=${value}
    maxlength="40"
    aria-label="Folder name"
    spellcheck="false"
    onInput=${(e) => setValue(e.currentTarget.value)}
    onBlur=${save}
    onKeyDown=${(e) => {
      if (e.key === "Enter") e.currentTarget.blur();
      if (e.key === "Escape") {
        setValue(folder.name);
        e.stopPropagation();
        setTimeout(() => e.target.blur());
      }
    }}
  />`;
}

function FolderOverlay({ draft }) {
  const state = getState();
  const open = state.openFolder;
  const found = open && findFolder(draft, open.id);
  if (!found) return null;
  const folder = found.item;
  const page = Math.min(open.page, folder.pages.length - 1);
  const items = folder.pages[page] || [];
  return html`<div class="folder-overlay" onPointerDown=${(e) => e.target === e.currentTarget && actions.closeFolder()}>
    <div class="folder-head" style=${{ top: `${L.FOLDER_TOP - 78}px` }}>
      <${FolderTitle} folder=${folder} />
    </div>
    <div
      class="folder-panel"
      style=${{ left: `${L.FOLDER_LEFT}px`, top: `${L.FOLDER_TOP}px`, width: `${L.FOLDER_W}px`, height: `${L.FOLDER_H}px` }}
    >
      ${items.map(
        (item, i) =>
          html`<${HomeItem}
            key=${item.id}
            item=${item}
            box=${L.folderBox(i)}
            where=${{ c: { s: "folder", fid: folder.id, fp: page }, i }}
          />`,
      )}
    </div>
    ${folder.pages.length > 1
      ? html`<div class="folder-dots" style=${{ top: `${L.FOLDER_TOP + L.FOLDER_H + 16}px` }}>
          ${folder.pages.map(
            (_, i) =>
              html`<button
                class=${`dot${i === page ? " is-current" : ""}`}
                aria-label=${`Folder page ${i + 1}`}
                onClick=${() => setState({ openFolder: { ...open, page: i } })}
              ></button>`,
          )}
        </div>`
      : null}
  </div>`;
}

const statusIcons = html`<div class="status-icons" aria-hidden="true">
  <svg viewBox="0 0 18 12" class="signal">
    <rect x="0" y="8" width="3" height="4" rx="1" /><rect x="5" y="5.5" width="3" height="6.5" rx="1" />
    <rect x="10" y="3" width="3" height="9" rx="1" /><rect x="15" y="0" width="3" height="12" rx="1" />
  </svg>
  <svg viewBox="0 0 16 12" class="wifi">
    <path d="M8 11.2 5.6 8.6a3.4 3.4 0 0 1 4.8 0z" /><path d="M3.4 6.4a6.5 6.5 0 0 1 9.2 0l-1.4 1.5a4.5 4.5 0 0 0-6.4 0z" />
    <path d="M1 4.1a9.9 9.9 0 0 1 14 0l-1.4 1.5a7.9 7.9 0 0 0-11.2 0z" />
  </svg>
  <svg viewBox="0 0 27 13" class="battery">
    <rect x="0.5" y="0.5" width="23" height="12" rx="3.5" fill="none" stroke="currentColor" opacity=".45" />
    <rect x="2" y="2" width="20" height="9" rx="2.2" /><path d="M25 4.5v4a2 2 0 0 0 0-4z" opacity=".45" />
  </svg>
</div>`;

// The phone's own wallpaper when it sent one; the flat dusk colour until then, or if not.
function Wallpaper() {
  const version = getState().wallpaper;
  const [failed, setFailed] = useState(null);
  const shown = version && failed !== version;
  return html`<div class=${`wallpaper${shown ? " has-image" : ""}`}>
    ${shown
      ? html`<img
          class="wallpaper-img"
          src=${wallpaperUrl(version)}
          alt=""
          draggable="false"
          onError=${() => setFailed(version)}
        />`
      : null}
  </div>`;
}

function Skeleton() {
  return html`<div class="skeleton">
    ${Array.from({ length: 20 }, (_, i) => {
      const box = L.cellBox({ col: i % 4, row: Math.floor(i / 4), w: 1, h: 1 });
      return html`<div class="skeleton-icon" style=${{ transform: `translate(${box.x}px, ${box.y}px)` }}></div>`;
    })}
  </div>`;
}

function ScreenMessage() {
  const state = getState();
  const job = state.job;
  const reading = job && job.kind === "read" && job.state === "running";
  const error = state.server?.error;
  if (state.draft && !reading) return null;
  if (state.draft && reading) return null;
  if (reading || state.boot === "loading") {
    const last = job?.events?.[job.events.length - 1];
    return html`<div class="screen-message">
      <${Skeleton} />
      <div class="screen-card">
        <div class="spinner"></div>
        <div class="screen-card-title">Reading your iPhone</div>
        <div class="screen-card-text">${last?.message || "Connecting..."}</div>
        <div class="screen-card-note">Read-only. Nothing is written until you press Apply.</div>
      </div>
    </div>`;
  }
  if (error) {
    return html`<div class="screen-message">
      <div class="screen-card is-error">
        <div class="screen-card-icon">!</div>
        <div class="screen-card-title">${error.title}</div>
        ${error.steps?.length
          ? html`<ol class="screen-steps">${error.steps.map((step) => html`<li>${renderCode(step)}</li>`)}</ol>`
          : null}
        <button class="btn btn-primary" onClick=${() => actions.readFromPhone({ confirmed: true })}>Try again</button>
        ${error.detail ? html`<details class="screen-detail"><summary>Details</summary><code>${error.detail}</code></details>` : null}
      </div>
    </div>`;
  }
  return null;
}

// `code` spans in friendly messages.
export function renderCode(text) {
  return text.split(/(`[^`]+`)/).map((part) => (part.startsWith("`") ? html`<code>${part.slice(1, -1)}</code>` : part));
}

function PageControls({ pageCount, page, draft }) {
  const state = getState();
  const items = draft?.pages[page] || [];
  const used = L.pageCells(items);
  const issuePages = new Set(
    (state.check.issues || []).filter((i) => i.location?.section === "page").map((i) => i.location.page - 1),
  );
  const empty = draft && !items.length;
  return html`<div class="page-controls">
    <div class="pager">
      <button
        class="round-btn"
        aria-label="Previous page"
        data-zone="flip"
        data-flip="prev"
        disabled=${page <= 0}
        onClick=${() => actions.goToPage(page - 1)}
      >
        <svg viewBox="0 0 16 16"><path d="M10 3 5 8l5 5" /></svg>
      </button>
      <div class="dots" role="tablist" aria-label="Pages">
        ${Array.from({ length: pageCount }, (_, i) => {
          const isNew = draft && i >= draft.pages.length;
          return html`<button
            role="tab"
            aria-selected=${i === page}
            aria-label=${isNew ? "New page" : `Page ${i + 1}`}
            class=${`dot${i === page ? " is-current" : ""}${issuePages.has(i) ? " has-issue" : ""}${isNew ? " is-new" : ""}`}
            data-zone="flip"
            data-flip=${String(i)}
            onClick=${() => actions.goToPage(i)}
          ></button>`;
        })}
      </div>
      <button
        class="round-btn"
        aria-label="Next page"
        data-zone="flip"
        data-flip="next"
        disabled=${page >= pageCount - 1}
        onClick=${() => actions.goToPage(page + 1)}
      >
        <svg viewBox="0 0 16 16"><path d="m6 3 5 5-5 5" /></svg>
      </button>
    </div>
    ${draft
      ? html`<div class="page-tools">
          <span class=${`page-info${used > L.PAGE_CELLS ? " is-over" : ""}`}>
            Page ${page + 1} of ${draft.pages.length}, ${used} of ${L.PAGE_CELLS} cells used
          </span>
          <button class="chip-btn" onClick=${actions.addPage} title="Add an empty page after this one">
            <svg viewBox="0 0 16 16"><path d="M8 3v10M3 8h10" /></svg>Add page
          </button>
          ${empty && draft.pages.length > 1
            ? html`<button class="chip-btn" onClick=${actions.removePage} title="Remove this empty page">
                <svg viewBox="0 0 16 16"><path d="M3 8h10" /></svg>Remove page
              </button>`
            : null}
        </div>`
      : null}
  </div>`;
}

export function Phone() {
  const state = useStore();
  const stage = useRef(null);
  const [scale, setScale] = useState(0.8);
  useLayoutEffect(() => {
    const element = stage.current;
    const fit = () => {
      const width = element.clientWidth - 24;
      const height = element.clientHeight - 96;
      setScale(Math.max(0.42, Math.min(width / (FRAME_W + 16), height / FRAME_H, 1.08)));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const view = state.draft ? displayed(state) : null;
  const draft = view?.draft;
  const realPages = draft ? draft.pages.length : 1;
  const pageCount = Math.max(realPages, state.dragPages || 0, 1);
  const page = Math.min(state.page, pageCount - 1);
  const items = draft?.pages[page] || [];
  const target = state.drag?.target;
  const dockBlocked = target?.invalid && target.c?.s === "dock";
  const pageBlocked = target?.invalid && target.c?.s === "page";
  const dockIssue = (state.check.issues || []).some((i) => i.location?.section === "dock");

  return html`<div class="stage" ref=${stage}>
    <div class="phone-box" style=${{ width: `${FRAME_W * scale}px`, height: `${FRAME_H * scale}px` }}>
      <div class="phone" style=${{ transform: `scale(${scale})` }}>
        <span class="side-btn side-action"></span><span class="side-btn side-up"></span>
        <span class="side-btn side-down"></span><span class="side-btn side-power"></span>
        <div class=${`screen${state.openFolder ? " has-folder" : ""}`} data-zone="screen">
          <${Wallpaper} />
          <div class="status-bar">
            <span class="clock">9:41</span>
            <span class="island"></span>
            ${statusIcons}
          </div>
          ${draft
            ? html`<div class=${`home${state.openFolder ? " is-dimmed" : ""}${pageBlocked ? " is-blocked" : ""}`}>
                <${PageGrid} key=${`page-${page}`} items=${items} page=${page} highlight=${view.highlight} />
                <div class="screen-dots">
                  ${Array.from({ length: pageCount }, (_, i) => html`<span class=${i === page ? "is-current" : ""}></span>`)}
                </div>
                <${Dock} items=${draft.dock} highlight=${view.highlight} blocked=${dockBlocked || dockIssue} />
              </div>`
            : null}
          ${draft ? html`<${FolderOverlay} draft=${draft} />` : null}
          <${ScreenMessage} />
          <div class="home-bar"></div>
        </div>
      </div>
    </div>
    <${PageControls} pageCount=${pageCount} page=${page} draft=${draft} />
  </div>`;
}
