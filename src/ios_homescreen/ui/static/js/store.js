// A tiny global store: one state object, shallow updates, subscribers re-render.

import { useEffect, useReducer } from "preact/hooks";

let state = {};
const listeners = new Set();

export function getState() {
  return state;
}

export function setState(update) {
  const patch = typeof update === "function" ? update(state) : update;
  if (!patch) return;
  state = { ...state, ...patch };
  for (const listener of listeners) listener(state);
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function initState(initial) {
  state = initial;
}

// Re-render the calling component on every store change.
export function useStore() {
  const [, force] = useReducer((n) => n + 1, 0);
  useEffect(() => subscribe(() => force(0)), []);
  return state;
}
