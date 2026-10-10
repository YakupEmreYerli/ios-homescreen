// Modal dialogs (apply, progress, backups, confirmations), the context menu and toasts.

import { useEffect, useRef, useState } from "preact/hooks";
import * as actions from "./actions.js";
import { html } from "./html.js";
import { describeChange, formatDate, issueText, kindName, plural, relativeTime } from "./messages.js";
import { REMOVABLE, STUCK, allItems, blockReason, locate, removeId } from "./ops.js";
import { renderCode } from "./phone.js";
import { getState, setState, useStore } from "./store.js";

function close() {
  setState({ dialog: null });
}

function Modal({ title, children, tone = "", wide = false, onClose = close, dismissable = true }) {
  const box = useRef(null);
  useEffect(() => {
    const focusable = box.current?.querySelector("[data-autofocus]") || box.current?.querySelector("button");
    focusable?.focus();
    const key = (event) => {
      if (event.key === "Escape" && dismissable) onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [dismissable]);
  return html`<div class="modal-backdrop" onPointerDown=${(e) => dismissable && e.target === e.currentTarget && onClose()}>
    <div class=${`modal${wide ? " is-wide" : ""}${tone ? ` tone-${tone}` : ""}`} role="dialog" aria-modal="true" aria-label=${title} ref=${box}>
      ${children}
    </div>
  </div>`;
}

const STEPS = [
  { step: 1, label: "Read the phone and save a backup" },
  { step: 2, label: "Build the layout" },
  { step: 3, label: "Write it to the phone" },
  { step: 4, label: "Read it back to check" },
  { step: 5, label: "Done" },
];

const check = html`<svg viewBox="0 0 20 20"><path d="m5 10.5 3.2 3L15 6.5" /></svg>`;

function ApplyDialog() {
  const state = getState();
  const changes = state.check.changes || [];
  const summary = state.check.summary || {};
  const device = state.server?.device?.name || "the iPhone";
  const removed = changes.filter((c) => c.kind === "removed");
  const widgets = state.draft && allItems(state.draft).some((item) => item.type === "widget");
  const lines = changes.slice(0, 8).map((change) => describeChange(change, state.draft));
  return html`<${Modal} title="Apply changes">
    <h3 class="modal-title">Apply ${plural(changes.length, "change")} to ${device}?</h3>
    <ul class="apply-lines">
      ${lines.map(
        (line) =>
          html`<li class=${`tone-${line.tone}`}><strong>${line.title}</strong>${" "}<span>${line.detail}</span></li>`,
      )}
      ${changes.length > lines.length ? html`<li class="more">and ${changes.length - lines.length} more</li>` : null}
    </ul>
    ${summary.to_library?.length || summary.to_home_screen?.length
      ? html`<p class="apply-counts">
          ${summary.to_home_screen?.length ? `${plural(summary.to_home_screen.length, "app")} ${summary.to_home_screen.length === 1 ? "comes" : "come"} to the home screen. ` : ""}
          ${summary.to_library?.length ? `${plural(summary.to_library.length, "app")} ${summary.to_library.length === 1 ? "goes" : "go"} to the App Library and ${summary.to_library.length === 1 ? "stays" : "stay"} installed.` : ""}
        </p>`
      : null}
    ${removed.length
      ? html`<div class="callout tone-danger">
          After you apply, the only way to get ${removed.length === 1 ? "this widget" : "these widgets"} back is to add ${removed.length === 1 ? "it" : "them"} again on the iPhone or to restore the backup.
        </div>`
      : null}
    ${widgets
      ? html`<div class="callout">
          Widgets where you chose what they show may go back to their default choice after the write.
        </div>`
      : null}
    <ol class="safety">
      <li><span>1</span>Backup</li>
      <li><span>2</span>Write</li>
      <li><span>3</span>Check by reading it back</li>
      <li><span>4</span>Roll back if it does not match</li>
    </ol>
    <div class="modal-actions">
      <button class="btn" onClick=${close}>Cancel</button>
      <button class="btn btn-commit" data-autofocus onClick=${() => actions.startApply()}>Apply</button>
    </div>
  <//>`;
}

function JobDialog() {
  const state = getState();
  const job = state.job;
  const dialog = state.dialog;
  if (!job) return null;
  const running = job.state === "running";
  const events = job.events || [];
  const reached = Math.max(0, ...events.filter((e) => e.step && e.total === 5).map((e) => e.step));
  const status = job.result?.status;
  const error = job.error;
  const what = dialog.jobKind === "restore" ? "Restore" : "Apply";
  let outcome = null;
  if (!running && status === "applied") {
    outcome = html`<div class="outcome tone-success">
      <div class="outcome-icon">${check}</div>
      <div>
        <h3>${dialog.jobKind === "restore" ? "Backup restored and verified" : "Applied and verified"}</h3>
        <p>The phone was read back and matches. The backup is kept as ${job.result.backup_name}.</p>
      </div>
    </div>`;
  } else if (!running && status === "rolled-back") {
    outcome = html`<div class="outcome tone-warning">
      <div class="outcome-icon">↺</div>
      <div>
        <h3>Rolled back</h3>
        <p>The phone did not show the new layout in time, so the backup was written back and verified. Your edits are still here; you can try again.</p>
      </div>
    </div>`;
  } else if (!running && status === "rollback-failed") {
    outcome = html`<div class="outcome tone-danger">
      <div class="outcome-icon">!</div>
      <div>
        <h3>The rollback could not be verified</h3>
        <p>Check the phone. The backup is kept as ${job.result.backup_name}; restore it from Backups.</p>
      </div>
    </div>`;
  } else if (!running && error) {
    outcome = html`<div class="outcome tone-danger">
      <div class="outcome-icon">!</div>
      <div>
        <h3>${error.title}</h3>
        ${error.code !== "layout_changed" ? html`<p>Nothing was written unless the steps above say so.</p>` : null}
        ${error.steps?.length ? html`<ol class="screen-steps">${error.steps.map((s) => html`<li>${renderCode(s)}</li>`)}</ol>` : null}
        ${error.detail ? html`<details class="screen-detail"><summary>Details</summary><code>${error.detail}</code></details>` : null}
      </div>
    </div>`;
  }
  const reread = job.result?.reread_error;
  return html`<${Modal} title=${`${what} progress`} dismissable=${!running} wide>
    <h3 class="modal-title">${running ? `${what === "Apply" ? "Applying" : "Restoring"}...` : what}</h3>
    <ol class="stepper">
      ${STEPS.map(({ step, label }) => {
        const failedCheck = step === 4 && (status === "rolled-back" || status === "rollback-failed");
        const done = !failedCheck && (reached > step || (reached === step && step === 5) || (!running && status === "applied"));
        const active = running && (reached === step || (reached === 0 && step === 1));
        return html`<li class=${`${done ? "is-done" : ""}${active ? " is-active" : ""}${failedCheck ? " is-failed" : ""}`}>
          <span class="step-mark">${done ? check : failedCheck ? "!" : active ? html`<span class="spinner small"></span>` : step}</span>
          <span>${label}</span>
        </li>`;
      })}
    </ol>
    <div class="event-log" aria-live="polite">
      ${events.slice(-6).map((e) => html`<div class=${`event level-${e.level}`}>${e.message}</div>`)}
    </div>
    ${outcome}
    ${reread ? html`<div class="callout">Reading the phone afterwards failed: ${reread.title}. Use Read from phone.</div>` : null}
    <div class="modal-actions">
      ${!running && error?.code === "layout_changed"
        ? html`<button class="btn" onClick=${() => actions.readFromPhone()}>Read from phone</button>
            <button class="btn btn-danger" onClick=${() => actions.startApply({ force: true })}>Apply anyway</button>`
        : null}
      ${!running && status === "rollback-failed"
        ? html`<button class="btn" onClick=${actions.openBackups}>Open Backups</button>`
        : null}
      ${!running && status === "rolled-back"
        ? html`<button class="btn" onClick=${() => actions.startApply()}>Try again</button>`
        : null}
      <button class="btn btn-primary" disabled=${running} onClick=${close}>${running ? "Working..." : "Done"}</button>
    </div>
  <//>`;
}

function BackupsDialog() {
  const state = getState();
  const backups = state.dialog.backups;
  const [asking, setAsking] = useState(null);
  const running = state.job?.state === "running";
  const showcase = Boolean(state.server?.showcase);
  return html`<${Modal} title="Backups" wide>
    <h3 class="modal-title">Backups</h3>
    <p class="modal-text">A backup is saved before every write. Restoring one writes it to the phone with the same checks as Apply (and backs up the current layout first).</p>
    ${backups === null ? html`<div class="empty"><span class="spinner small"></span> Loading...</div>` : null}
    ${showcase ? html`<div class="empty">Showcase mode does not list backups and cannot restore them.</div>` : null}
    ${backups && !backups.length && !showcase ? html`<div class="empty">No backups yet. One is made before every Apply.</div>` : null}
    ${backups?.length
      ? html`<ul class="backup-list">
          ${backups.map(
            (b) => html`<li class=${asking === b.name ? "is-asking" : ""}>
              <div class="backup-main">
                <strong>${formatDate(b.created)}</strong>
                <span>${relativeTime(b.created)}${b.summary ? `, ${plural(b.summary.dock, "item")} in the dock, ${plural(b.summary.pages, "page")}, ${plural(b.summary.items, "item")} in all` : ""}</span>
                <span class="backup-file">${b.name}</span>
              </div>
              ${asking === b.name
                ? html`<div class="backup-confirm">
                    <span>Write this backup to the phone?</span>
                    <button class="btn" onClick=${() => setAsking(null)}>Cancel</button>
                    <button class="btn btn-primary" disabled=${running} onClick=${() => actions.restoreBackup(b.name)}>Restore</button>
                  </div>`
                : html`<button class="btn" disabled=${running} onClick=${() => setAsking(b.name)}>Restore...</button>`}
            </li>`,
          )}
        </ul>`
      : null}
    <div class="modal-actions"><button class="btn btn-primary" onClick=${close}>Close</button></div>
  <//>`;
}

function ConfirmRemove() {
  const { item } = getState().dialog;
  return html`<${Modal} title="Remove widget" tone="danger">
    <h3 class="modal-title">Remove the ${item.name} widget?</h3>
    <p class="modal-text">
      ios-homescreen can move widgets but cannot create them. After you apply, the only way back is to add it again on the iPhone (touch and hold the home screen, then Edit → Add Widget), or to restore a backup.
    </p>
    <div class="modal-actions">
      <button class="btn" data-autofocus onClick=${close}>Keep it</button>
      <button class="btn btn-danger" onClick=${actions.confirmRemove}>Remove widget</button>
    </div>
  <//>`;
}

function ConfirmRead() {
  return html`<${Modal} title="Read from phone">
    <h3 class="modal-title">Discard your edits and read the phone again?</h3>
    <p class="modal-text">Your changes have not been applied. Reading the phone replaces them with what is on it now.</p>
    <div class="modal-actions">
      <button class="btn" data-autofocus onClick=${close}>Keep editing</button>
      <button class="btn btn-danger" onClick=${() => actions.readFromPhone({ confirmed: true })}>Discard and read</button>
    </div>
  <//>`;
}

function ConfirmImport() {
  const { result, file } = getState().dialog;
  return html`<${Modal} title="Import layout" tone="danger">
    <h3 class="modal-title">${file} leaves out ${plural(result.removed.length, "widget")}</h3>
    <p class="modal-text">If you import it, these widgets are removed when you apply: ${result.removed.map((x) => x.name).join(", ")}. This tool cannot put them back.</p>
    <div class="modal-actions">
      <button class="btn" data-autofocus onClick=${close}>Cancel</button>
      <button class="btn btn-danger" onClick=${() => actions.useImported(result)}>Import and remove</button>
    </div>
  <//>`;
}

function ImportIssues() {
  const { issues, file } = getState().dialog;
  return html`<${Modal} title="Import problems">
    <h3 class="modal-title">${file} cannot be used as it is</h3>
    <ul class="issue-list">${issues.map((issue) => html`<li>${issueText(issue, actions.nameOf)}</li>`)}</ul>
    <div class="modal-actions"><button class="btn btn-primary" onClick=${close}>Close</button></div>
  <//>`;
}

// Showcase mode looks like the normal editor, so Apply explains instead of writing.
function ShowcaseNotice() {
  return html`<${Modal} title="Showcase mode">
    <h3 class="modal-title">Nothing is written in showcase mode</h3>
    <p class="modal-text">This editor was started with <code>--showcase</code> to show a layout file on this iPhone. It does not write to the phone. Start it without <code>--showcase</code> to apply changes.</p>
    <div class="modal-actions"><button class="btn btn-primary" data-autofocus onClick=${close}>OK</button></div>
  <//>`;
}

function ErrorDialog() {
  const { error } = getState().dialog;
  return html`<${Modal} title=${error.title}>
    <h3 class="modal-title">${error.title}</h3>
    ${error.steps?.length ? html`<ol class="screen-steps">${error.steps.map((s) => html`<li>${renderCode(s)}</li>`)}</ol>` : null}
    ${error.detail ? html`<details class="screen-detail"><summary>Details</summary><code>${error.detail}</code></details>` : null}
    <div class="modal-actions">
      <button class="btn" onClick=${close}>Close</button>
      <button class="btn btn-primary" onClick=${() => actions.readFromPhone({ confirmed: true })}>Try again</button>
    </div>
  <//>`;
}

export function Dialogs() {
  const state = useStore();
  const kind = state.dialog?.kind;
  if (kind === "apply") return html`<${ApplyDialog} />`;
  if (kind === "job") return html`<${JobDialog} />`;
  if (kind === "backups") return html`<${BackupsDialog} />`;
  if (kind === "confirm-remove") return html`<${ConfirmRemove} />`;
  if (kind === "confirm-read") return html`<${ConfirmRead} />`;
  if (kind === "confirm-import") return html`<${ConfirmImport} />`;
  if (kind === "import-issues") return html`<${ImportIssues} />`;
  if (kind === "error") return html`<${ErrorDialog} />`;
  if (kind === "showcase") return html`<${ShowcaseNotice} />`;
  return null;
}

// ------------------------------------------------------------------ context menu

function menuEntries(item) {
  const state = getState();
  const draft = state.draft;
  const where = locate(draft, item.id);
  if (!where) return [];
  const entries = [];
  const inFolder = where.c.s === "folder";
  if (item.type === "folder") {
    entries.push({ label: "Open", run: () => actions.openFolder(item.id) });
    entries.push({ label: "Rename", run: () => actions.openFolder(item.id, true) });
    entries.push({ label: "Unpack folder", run: () => actions.ungroupFolder(item) });
  }
  if (inFolder) {
    entries.push({ label: "Move out of the folder", run: () => actions.moveTo(item, { s: "page", p: state.page }) });
  }
  const base = removeId(draft, item.id).draft;
  const move = (label, c) => {
    const blocked = blockReason(base, item, c);
    entries.push({
      label: blocked ? `${label} (${blocked.code === "dock_full" ? "full" : "no room"})` : label,
      disabled: Boolean(blocked),
      run: () => actions.moveTo(item, c),
    });
  };
  if (!inFolder && where.c.s !== "dock" && item.type !== "widget") move("Move to the dock", { s: "dock" });
  draft.pages.forEach((_, p) => {
    const samePlace = where.c.s === "page" && where.c.p === p;
    if (!samePlace) move(`Move to page ${p + 1}`, { s: "page", p });
  });
  if (!inFolder && item.type !== "folder" && item.type !== "widget") {
    entries.push({ label: "Put in a new folder", run: () => actions.intoNewFolder(item) });
  }
  entries.push({ separator: true });
  if (item.type === "app") entries.push({ label: "Move to App Library", run: () => actions.sendAway(item) });
  if (item.type === "folder") entries.push({ label: "Move its apps to App Library", run: () => actions.sendAway(item) });
  if (REMOVABLE.has(item.type)) entries.push({ label: "Remove widget...", danger: true, run: () => actions.sendAway(item) });
  if (STUCK.has(item.type)) {
    entries.push({ label: `Why can't I remove this ${kindName(item.type)}?`, run: () => actions.sendAway(item) });
  }
  return entries;
}

export function ContextMenu() {
  const state = useStore();
  const menu = state.menu;
  const box = useRef(null);
  const [position, setPosition] = useState(null);
  useEffect(() => {
    if (!menu) return undefined;
    const away = (event) => {
      if (!box.current?.contains(event.target)) setState({ menu: null });
    };
    const key = (event) => event.key === "Escape" && setState({ menu: null });
    window.addEventListener("pointerdown", away, true);
    window.addEventListener("keydown", key);
    window.addEventListener("resize", away);
    return () => {
      window.removeEventListener("pointerdown", away, true);
      window.removeEventListener("keydown", key);
      window.removeEventListener("resize", away);
    };
  }, [menu]);
  useEffect(() => {
    if (!menu || !box.current) return setPosition(null);
    const rect = box.current.getBoundingClientRect();
    setPosition({
      x: Math.min(menu.x, window.innerWidth - rect.width - 8),
      y: Math.min(menu.y, window.innerHeight - rect.height - 8),
    });
  }, [menu]);
  if (!menu) return null;
  const entries = menuEntries(menu.item);
  const style = { left: `${(position || menu).x}px`, top: `${(position || menu).y}px`, visibility: position ? "visible" : "hidden" };
  return html`<div class="menu" role="menu" ref=${box} style=${style}>
    <div class="menu-title">${menu.item.name}</div>
    ${entries.map((entry) =>
      entry.separator
        ? html`<div class="menu-sep"></div>`
        : html`<button
            role="menuitem"
            disabled=${entry.disabled}
            class=${`menu-item${entry.danger ? " is-danger" : ""}`}
            onClick=${() => {
              setState({ menu: null });
              entry.run();
            }}
          >
            ${entry.label}
          </button>`,
    )}
  </div>`;
}

// ------------------------------------------------------------------ toasts

export function Toasts() {
  const state = useStore();
  return html`<div class="toasts" aria-live="polite">
    ${state.toasts.map(
      (t) => html`<div class=${`toast tone-${t.tone}`} key=${t.id}>
        <span>${t.text}</span>
        ${t.action
          ? html`<button class="toast-action" onClick=${() => {
              actions.dismissToast(t.id);
              t.action.run();
            }}>${t.action.label}</button>`
          : null}
        <button class="toast-close" aria-label="Dismiss" onClick=${() => actions.dismissToast(t.id)}>×</button>
      </div>`,
    )}
  </div>`;
}

