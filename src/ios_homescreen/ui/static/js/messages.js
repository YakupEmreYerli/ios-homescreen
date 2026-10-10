// Plain-language text for planner issue codes, changes and places.

import { rowCol } from "./layout.js";

const quote = (text) => `“${text}”`;

// Why a drop was refused, in a few words (shown on the dragged icon).
export function refusalShort(problem) {
  return (
    {
      dock_full: "The dock is full",
      page_full: "This page is full",
      widget_in_dock: "Widgets can't go in the dock",
      widget_in_folder: "Widgets can't go in folders",
      nested_folder: "Folders can't go in folders",
      not_removable: "Can't be removed from here",
      folder_to_library: "Open the folder first",
    }[problem?.code] || "Can't go here"
  );
}

// A refused drop, as a sentence.
export function refusalText(problem, nameOf = (id) => id) {
  const d = problem.details || {};
  switch (problem.code) {
    case "dock_full":
      return `The dock is full: it holds ${d.capacity ?? 4} items. Take one out first.`;
    case "page_full":
      return `Page ${problem.location?.page ?? ""} is full: ${d.capacity ?? 24} of ${d.capacity ?? 24} cells are used. Make room or add a page.`;
    case "folder_to_library":
      return "Open the folder to send its apps to the App Library.";
    default:
      return issueText(problem, nameOf);
  }
}

// Plain sentence for a planner issue ({code, message, location, details}).
export function issueText(issue, nameOf = (id) => id) {
  const d = issue.details || {};
  const where = issue.location || {};
  const name = d.id ? quote(nameOf(d.id)) : "An item";
  switch (issue.code) {
    case "dock_full":
      return `The dock holds ${d.capacity ?? 4} items. Take ${(d.count ?? 5) - (d.capacity ?? 4)} out of it.`;
    case "page_full":
      return `Page ${where.page ?? "?"} is over capacity: ${d.cells} of ${d.capacity ?? 24} cells. Move something to another page.`;
    case "widget_in_dock":
      return "Widgets can't go in the dock.";
    case "widget_in_folder":
      return "Widgets can't go in folders.";
    case "nested_folder":
      return "A folder can't go inside another folder.";
    case "folder_name_missing":
      return "Every folder needs a name.";
    case "empty_folder":
    case "empty_folder_page":
      return `Folder ${quote(where.folder || "")} has an empty page.`;
    case "duplicate_item":
      return `${name} is on the home screen more than once.`;
    case "unknown_app":
      return `${name} is not installed on this iPhone.`;
    case "unknown_item":
      return `${name} is not on this iPhone. Widgets, web clips and web apps can be moved or removed, but not created.`;
    case "wrong_kind":
      return `${name} is a ${d.kind}, not what the layout says.`;
    case "ambiguous_name":
      return `${quote(d.name)} matches several apps; the layout must use the bundle id.`;
    case "not_removable": {
      const how = d.kind === "webapp" ? "touch and hold it, then delete it" : "touch and hold it, then Delete Bookmark";
      const what = d.kind === "webapp" ? "web apps" : "web clips";
      return `${quote(d.name || nameOf(d.id))} can't be removed from here: the iPhone puts ${what} back. Delete it on the iPhone (${how}), then read again.`;
    }
    case "removal_not_allowed": {
      const ids = d.ids || [];
      return `Removing ${ids.map((id) => quote(nameOf(id))).join(", ")} needs your confirmation.`;
    }
    case "invalid_toml":
      return `The file is not valid TOML: ${issue.message.replace(/^invalid TOML: /, "")}`;
    default:
      return issue.message ? issue.message[0].toUpperCase() + issue.message.slice(1) : issue.code;
  }
}

const KIND_NAMES = {
  app: "app",
  folder: "folder",
  widget: "widget",
  webclip: "web clip",
  webapp: "web app",
};

export function kindName(type) {
  return KIND_NAMES[type] || "item";
}

// Where a change puts an item, as the user sees it: "page 1, row 5, column 2".
function destination(where, id, draft, pageIndex) {
  if (!where) return "";
  if (where.folder) return `the ${quote(where.folder)} folder`;
  if (where.section === "dock") return `the dock, position ${where.index}`;
  const index = pageIndex(where.page);
  const spot = index == null ? null : rowCol(draft.pages[index] || [], id);
  return spot ? `page ${where.page}, row ${spot.row}, column ${spot.col}` : `page ${where.page}`;
}

// { title, detail, tone } for one change from the server: the item's name and, in
// plain words, what happens to it.
export function describeChange(change, draft) {
  const nonEmpty = draft.pages.map((p, i) => (p.length ? i : null)).filter((i) => i !== null);
  const pageIndex = (page) => nonEmpty[page - 1] ?? null;
  const to = () => destination(change.to, change.id, draft, pageIndex);
  const name = change.name || kindName(change.type);
  switch (change.kind) {
    case "added":
      if (change.type && change.type !== "app") return { title: name, detail: `Added to ${to()}`, tone: "add" };
      return { title: name, detail: `Comes from the App Library to ${to()}`, tone: "add" };
    case "moved":
    case "reordered":
      return { title: name, detail: `Moves to ${to()}`, tone: "move" };
    case "to_library":
      return { title: name, detail: "Goes to the App Library", tone: "library" };
    case "removed":
      return { title: name, detail: `${kindName(change.type)[0].toUpperCase()}${kindName(change.type).slice(1)} removed. This tool cannot put it back.`, tone: "danger" };
    case "folder_created":
      return { title: name, detail: `New folder on ${to()}`, tone: "add" };
    case "folder_renamed":
      return { title: name, detail: `Folder renamed from ${quote(change.old_name)}`, tone: "move" };
    case "folder_deleted":
      return { title: name, detail: "Folder removed", tone: "library" };
    case "pages":
      return { title: "Pages", detail: `${change.before} pages become ${change.after}`, tone: "move" };
    default:
      return { title: name, detail: change.kind, tone: "move" };
  }
}

export function plural(count, one, many = `${one}s`) {
  return `${count} ${count === 1 ? one : many}`;
}

export function relativeTime(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  const seconds = Math.round((Date.now() - then.getTime()) / 1000);
  if (Number.isNaN(seconds)) return "";
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${plural(minutes, "minute")} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${plural(hours, "hour")} ago`;
  const days = Math.round(hours / 24);
  return `${plural(days, "day")} ago`;
}

export function formatDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
