// Dependency-free frontend security regression checks.

import assert from "node:assert/strict";
import test from "node:test";

globalThis.HTMLElement = class {};
globalThis.customElements = {
  define() {},
  get() { return undefined; },
};

const { escapeHtml } = await import(
  "../custom_components/shelly_toolkit/frontend/shelly-toolkit-panel.js"
);

test("panel escapes device and RPC output before rendering", () => {
  assert.equal(
    escapeHtml('<img src=x onerror="alert(1)">&'),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;",
  );
});
