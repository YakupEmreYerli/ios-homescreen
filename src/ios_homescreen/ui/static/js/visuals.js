// How items look: app icons (real ones from the phone, or a placeholder), folders,
// widgets, web clips and web apps.

import { html } from "./html.js";
import { useEffect, useState } from "preact/hooks";
import { iconUrl } from "./api.js";
import { getState } from "./store.js";

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// A flat, muted colour per id for icons that have not arrived yet.
export function placeholderColor(id) {
  const hue = hash(id || "?") % 360;
  return `hsl(${hue} 32% 46%)`;
}

function initial(name) {
  const letter = (name || "?").trim().match(/[\p{L}\p{N}]/u);
  return letter ? letter[0].toUpperCase() : "?";
}

export function hasIcon(id) {
  return getState().icons.available.has(id);
}

// The icon square. `id` picks the image; `name` the placeholder letter.
export function Icon({ id, name, kind = "app", dim = false }) {
  const [failed, setFailed] = useState(false);
  const available = hasIcon(id) && !failed;
  useEffect(() => setFailed(false), [id]);
  if (available) {
    return html`<img
      class=${`icon-img${dim ? " is-dim" : ""}`}
      src=${iconUrl(id)}
      alt=""
      draggable="false"
      loading="lazy"
      onError=${() => setFailed(true)}
    />`;
  }

  const glyph = kind === "webclip" || kind === "webapp" ? globe : null;
  return html`<div
    class=${`icon-fallback${dim ? " is-dim" : ""}`}
    style=${{ background: placeholderColor(id) }}
  >
    ${glyph || html`<span>${initial(name)}</span>`}
  </div>`;
}

const globe = html`<svg viewBox="0 0 24 24" class="glyph" aria-hidden="true">
  <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.6" />
  <ellipse cx="12" cy="12" rx="3.6" ry="8.5" fill="none" stroke="currentColor" stroke-width="1.4" />
  <path d="M3.5 12h17M5 8h14M5 16h14" stroke="currentColor" stroke-width="1.3" fill="none" />
</svg>`;

const cloud = html`<svg viewBox="0 0 24 24" aria-hidden="true">
  <path d="M7.5 18h9.2a3.8 3.8 0 0 0 .4-7.6A5.2 5.2 0 0 0 7 9.6 4.2 4.2 0 0 0 7.5 18z" fill="currentColor" />
  <path d="M12 10.5v5m0 0-2-2m2 2 2-2" stroke="#1d2433" stroke-width="1.6" fill="none" stroke-linecap="round" />
</svg>`;

export function ItemIcon({ item }) {
  if (item.type === "folder") return html`<${FolderIcon} item=${item} />`;
  if (item.type === "widget") {
    const app = item.apps?.[0] || item.id;
    return html`<${Icon} id=${app} name=${item.name} />`;
  }
  return html`<${Icon} id=${item.id} name=${item.name} kind=${item.type} dim=${item.offloaded} />`;
}

export function FolderIcon({ item }) {
  const first = (item.pages[0] || []).slice(0, 9);
  return html`<div class="folder-icon">
    <div class="folder-grid">
      ${first.map(
        (inner) => html`<div class="folder-mini" key=${inner.id}><${ItemIcon} item=${inner} /></div>`,
      )}
    </div>
  </div>`;
}

// Badges for items that are not plain apps.
export function Badge({ item }) {
  if (item.offloaded) return html`<span class="badge badge-cloud" title="Offloaded: the app is not on the phone, only its icon">${cloud}</span>`;
  if (item.type === "webclip") return html`<span class="badge" title="Web clip">${globe}</span>`;
  if (item.type === "webapp") return html`<span class="badge" title="Web app">${globe}</span>`;
  return null;
}

function appName(id) {
  return getState().apps.find((app) => app.id === id)?.name || id;
}

const SIZE_NAMES = { small: "Small", medium: "Medium", large: "Large", extraLarge: "Extra large" };

// Widgets cannot be drawn as they look on the phone; a plain tile of the real size says
// which app it belongs to and what it is.
export function WidgetTile({ item }) {
  const app = item.apps?.[0] || null;
  const stack = item.stack && item.apps.length > 1;
  const size = SIZE_NAMES[item.size] || item.size;
  return html`<div class=${`widget-tile widget-${item.size}`}>
    <div class="widget-icon">${app ? html`<${Icon} id=${app} name=${item.name} />` : null}</div>
    <div class="widget-text">
      <div class="widget-name">${stack ? appName(app) : item.name}</div>
      <div class="widget-kind">${stack ? `${size} stack of ${item.apps.length}` : `${size} widget`}</div>
    </div>
  </div>`;
}

export function Visual({ item }) {
  if (item.type === "widget") return html`<${WidgetTile} item=${item} />`;
  if (item.type === "folder") return html`<${FolderIcon} item=${item} />`;
  return html`<${Icon} id=${item.id} name=${item.name} kind=${item.type} dim=${item.offloaded} />`;
}
