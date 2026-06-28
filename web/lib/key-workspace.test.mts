// Pure tests for the /keys workspace grouping + filtering (F137). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_WORKSPACE,
  workspaceOf,
  distinctWorkspaces,
  hasMultipleWorkspaces,
  parseWorkspaceFilter,
  filterByWorkspace,
  workspaceChipLabel,
} from "./key-workspace.ts";

const keys = [
  { workspace_id: "acme" },
  { workspace_id: "default" },
  { workspace_id: "" },
  { workspace_id: undefined },
  { workspace_id: "  beta  " },
  { workspace_id: "acme" },
];

test("workspaceOf collapses blank/unset/default into one bucket", () => {
  assert.equal(workspaceOf({ workspace_id: "default" }), "default");
  assert.equal(workspaceOf({ workspace_id: "" }), "default");
  assert.equal(workspaceOf({ workspace_id: undefined }), "default");
  assert.equal(workspaceOf({ workspace_id: null }), "default");
  assert.equal(workspaceOf({ workspace_id: "  beta  " }), "beta");
});

test("distinctWorkspaces counts and sorts default-first then alpha", () => {
  const w = distinctWorkspaces(keys);
  assert.deepEqual(
    w.map((x) => x.workspace),
    ["default", "acme", "beta"],
  );
  assert.equal(w.find((x) => x.workspace === "default")?.count, 3);
  assert.equal(w.find((x) => x.workspace === "acme")?.count, 2);
  assert.equal(w.find((x) => x.workspace === "beta")?.count, 1);
});

test("distinctWorkspaces is empty on empty / bad input", () => {
  assert.deepEqual(distinctWorkspaces([]), []);
  // @ts-expect-error bad input
  assert.deepEqual(distinctWorkspaces(null), []);
});

test("hasMultipleWorkspaces gates the chip to multi-tenant fleets", () => {
  assert.equal(hasMultipleWorkspaces(keys), true);
  assert.equal(hasMultipleWorkspaces([{ workspace_id: "acme" }]), false);
  assert.equal(
    hasMultipleWorkspaces([{ workspace_id: "" }, { workspace_id: "default" }]),
    false,
  );
});

test("parseWorkspaceFilter accepts a present workspace, rejects the rest", () => {
  assert.equal(parseWorkspaceFilter("acme", keys), "acme");
  assert.equal(parseWorkspaceFilter("default", keys), "default");
  assert.equal(parseWorkspaceFilter("ghost", keys), null);
  assert.equal(parseWorkspaceFilter("", keys), null);
  assert.equal(parseWorkspaceFilter(null, keys), null);
});

test("filterByWorkspace narrows to one bucket; null passes through", () => {
  assert.equal(filterByWorkspace(keys, "acme").length, 2);
  assert.equal(filterByWorkspace(keys, "default").length, 3); // default+blank+undef
  assert.equal(filterByWorkspace(keys, null).length, keys.length);
  assert.deepEqual(filterByWorkspace([], "acme"), []);
});

test("filterByWorkspace keeps unknown filter empty (no silent show-all)", () => {
  assert.equal(filterByWorkspace(keys, "ghost").length, 0);
});

test("workspaceChipLabel prefixes ws:", () => {
  assert.equal(workspaceChipLabel("acme"), "ws: acme");
  assert.equal(workspaceChipLabel(DEFAULT_WORKSPACE), "ws: default");
});
