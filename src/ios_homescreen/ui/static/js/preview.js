// What the phone shows while something is being dragged. The drag controller and the
// drop use the same functions, so what you see is what you get.

import { insert, removeId, tidyFolders } from "./ops.js";

// The draft without the dragged item (folders tidied, the open one kept).
export function baseFor(state) {
  const { draft, drag, openFolder } = state;
  const keep = openFolder ? openFolder.id : null;
  if (!drag || drag.fromLibrary) return tidyFolders(draft, keep);
  return tidyFolders(removeId(draft, drag.item.id).draft, keep);
}

// { draft, highlight } to render: the dragged item as a placeholder at its target.
export function displayed(state) {
  const { draft, drag, openFolder } = state;
  if (!drag) return { draft, highlight: null };
  const base = baseFor(state);
  const target = drag.target;
  if (!target || target.invalid || target.zone === "library") return { draft: base, highlight: null };
  if (target.zone === "merge") return { draft: base, highlight: target.targetId };
  const keep = openFolder ? openFolder.id : null;
  const placed = insert(base, target.c, target.index, { ...drag.item, ghost: true });
  return { draft: tidyFolders(placed, keep), highlight: null };
}
