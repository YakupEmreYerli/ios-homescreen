// htm bound to Preact: html`<div class=${x}>...</div>` instead of JSX, no build step.

import { h } from "preact";
import htm from "htm";

export const html = htm.bind(h);
