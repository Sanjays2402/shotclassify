// Pure tests for the /webhooks deliveries-filter URL persistence (F103). No
// DOM for the pure helpers; the browser wrappers run against a stubbed window.
import test from "node:test";
import assert from "node:assert/strict";

import {
  DELIVERY_STATUS_PARAM,
  DELIVERY_EVENT_PARAM,
  parseDeliveryFilterFromParams,
  hasDeliveryFilter,
  buildDeliveryFilterQuery,
  deliveryFilterUrl,
  buildDeliveryDeepLink,
  deliveryLinkToastMessage,
  readDeliveryFilterFromUrl,
  writeDeliveryFilterToUrl,
} from "./webhook-delivery-url.ts";

// A URLSearchParams-shaped stub from a plain record.
function params(rec: Record<string, string>) {
  return new URLSearchParams(rec);
}

test("param names are stable + delivery-prefixed", () => {
  assert.equal(DELIVERY_STATUS_PARAM, "dstatus");
  assert.equal(DELIVERY_EVENT_PARAM, "devent");
});

test("parse: a bare / null / parserless source yields the all-all default", () => {
  for (const src of [null, undefined, {} as never, params({})]) {
    assert.deepEqual(parseDeliveryFilterFromParams(src as never), {
      status: "all",
      event: "all",
    });
  }
});

test("parse: a known status passes through, case-insensitive + trimmed", () => {
  assert.deepEqual(
    parseDeliveryFilterFromParams(params({ dstatus: "  FAILED " })),
    { status: "failed", event: "all" },
  );
});

test("parse: an unknown status degrades to the all default", () => {
  assert.deepEqual(
    parseDeliveryFilterFromParams(params({ dstatus: "retrying" })),
    { status: "all", event: "all" },
  );
  // "all" itself is the inert default, not a constraint.
  assert.deepEqual(
    parseDeliveryFilterFromParams(params({ dstatus: "all" })),
    { status: "all", event: "all" },
  );
});

test("parse: any non-blank event token round-trips (open-ended event set)", () => {
  assert.deepEqual(
    parseDeliveryFilterFromParams(params({ devent: "classify.completed" })),
    { status: "all", event: "classify.completed" },
  );
  // A brand-new subscribed event the page has never hard-coded still parses.
  assert.deepEqual(
    parseDeliveryFilterFromParams(params({ devent: "future.event.v2" })),
    { status: "all", event: "future.event.v2" },
  );
});

test("parse: a blank / 'all' event degrades to the default", () => {
  assert.deepEqual(
    parseDeliveryFilterFromParams(params({ devent: "   " })),
    { status: "all", event: "all" },
  );
  assert.deepEqual(
    parseDeliveryFilterFromParams(params({ devent: "all" })),
    { status: "all", event: "all" },
  );
});

test("parse: an over-long event is capped at 128 chars", () => {
  const long = "e".repeat(500);
  const out = parseDeliveryFilterFromParams(params({ devent: long }));
  assert.equal(typeof out.event, "string");
  assert.equal((out.event as string).length, 128);
});

test("parse: both constraints together", () => {
  assert.deepEqual(
    parseDeliveryFilterFromParams(
      params({ dstatus: "pending", devent: "webhook.test" }),
    ),
    { status: "pending", event: "webhook.test" },
  );
});

test("hasDeliveryFilter: only true when something actually constrains", () => {
  assert.equal(hasDeliveryFilter({ status: "all", event: "all" }), false);
  assert.equal(hasDeliveryFilter({ status: "", event: "" }), false);
  assert.equal(hasDeliveryFilter({ status: "failed", event: "all" }), true);
  assert.equal(hasDeliveryFilter({ status: "all", event: "webhook.test" }), true);
  // An unknown status doesn't count as a constraint.
  assert.equal(hasDeliveryFilter({ status: "bogus", event: "all" }), false);
});

test("build: emits only active constraints, status before event", () => {
  assert.equal(buildDeliveryFilterQuery({ status: "all", event: "all" }), "");
  assert.equal(
    buildDeliveryFilterQuery({ status: "failed", event: "all" }),
    "dstatus=failed",
  );
  assert.equal(
    buildDeliveryFilterQuery({ status: "all", event: "webhook.test" }),
    "devent=webhook.test",
  );
  assert.equal(
    buildDeliveryFilterQuery({ status: "pending", event: "classify.completed" }),
    "dstatus=pending&devent=classify.completed",
  );
});

test("build -> parse round-trips every active-filter shape", () => {
  const shapes = [
    { status: "all", event: "all" },
    { status: "failed", event: "all" },
    { status: "all", event: "classify.completed" },
    { status: "success", event: "webhook.test" },
  ];
  for (const f of shapes) {
    const round = parseDeliveryFilterFromParams(
      params(Object.fromEntries(new URLSearchParams(buildDeliveryFilterQuery(f)))),
    );
    // Inactive slots normalise to "all" on parse, matching the page sentinel.
    assert.deepEqual(round, {
      status: f.status === "all" ? "all" : f.status,
      event: f.event === "all" ? "all" : f.event,
    });
  }
});

test("deliveryFilterUrl: cleans to the bare path when nothing's active", () => {
  assert.equal(
    deliveryFilterUrl("/webhooks", { status: "all", event: "all" }),
    "/webhooks",
  );
  assert.equal(
    deliveryFilterUrl("/webhooks", { status: "failed", event: "all" }),
    "/webhooks?dstatus=failed",
  );
  // A missing pathname defaults to /webhooks.
  assert.equal(
    deliveryFilterUrl("", { status: "pending", event: "all" }),
    "/webhooks?dstatus=pending",
  );
});

test("readDeliveryFilterFromUrl: SSR (no window) is the default", () => {
  assert.equal(typeof (globalThis as { window?: unknown }).window, "undefined");
  assert.deepEqual(readDeliveryFilterFromUrl(), { status: "all", event: "all" });
});

test("read/write round-trip through a stubbed window history + location", () => {
  const g = globalThis as { window?: unknown };
  let url = "/webhooks";
  g.window = {
    location: { pathname: "/webhooks", search: "" },
    history: {
      state: { k: 1 },
      replaceState: (_s: unknown, _t: string, next: string) => {
        url = next;
        const qi = next.indexOf("?");
        (g.window as any).location.search = qi >= 0 ? next.slice(qi) : "";
        (g.window as any).location.pathname =
          qi >= 0 ? next.slice(0, qi) : next;
      },
    },
  };
  try {
    // Writing an active filter rewrites the URL query in place.
    writeDeliveryFilterToUrl({ status: "failed", event: "webhook.test" });
    assert.equal(url, "/webhooks?dstatus=failed&devent=webhook.test");
    // Reading it back recovers the same filter.
    assert.deepEqual(readDeliveryFilterFromUrl(), {
      status: "failed",
      event: "webhook.test",
    });
    // Clearing the filter cleans the URL back to the bare path.
    writeDeliveryFilterToUrl({ status: "all", event: "all" });
    assert.equal(url, "/webhooks");
    assert.deepEqual(readDeliveryFilterFromUrl(), {
      status: "all",
      event: "all",
    });
  } finally {
    delete g.window;
  }
});

test("writeDeliveryFilterToUrl: a throwing History API is swallowed", () => {
  const g = globalThis as { window?: unknown };
  g.window = {
    location: { pathname: "/webhooks", search: "" },
    history: {
      state: null,
      replaceState: () => {
        throw new Error("blocked");
      },
    },
  };
  try {
    assert.doesNotThrow(() =>
      writeDeliveryFilterToUrl({ status: "failed", event: "all" }),
    );
  } finally {
    delete g.window;
  }
});

test("buildDeliveryDeepLink: bare filter returns just the base", () => {
  assert.equal(
    buildDeliveryDeepLink({ status: "all", event: "all" }),
    "/webhooks",
  );
  assert.equal(
    buildDeliveryDeepLink(
      { status: "all", event: "all" },
      "https://x.test/webhooks",
    ),
    "https://x.test/webhooks",
  );
});

test("buildDeliveryDeepLink: active filter appends the query, round-trips", () => {
  const url = buildDeliveryDeepLink(
    { status: "failed", event: "classify.completed" },
    "https://x.test/webhooks",
  );
  assert.ok(url.startsWith("https://x.test/webhooks?"));
  // The query parses back to the same constraints.
  const qs = url.slice(url.indexOf("?") + 1);
  const back = parseDeliveryFilterFromParams(new URLSearchParams(qs));
  assert.equal(back.status, "failed");
  assert.equal(back.event, "classify.completed");
});

test("deliveryLinkToastMessage: names the active constraints", () => {
  assert.equal(
    deliveryLinkToastMessage({ status: "failed", event: "classify.completed" }),
    "Copied a link to Failed classify.completed deliveries.",
  );
  assert.equal(
    deliveryLinkToastMessage({ status: "pending", event: "all" }),
    "Copied a link to Pending deliveries.",
  );
  assert.equal(
    deliveryLinkToastMessage({ status: "all", event: "shot.created" }),
    "Copied a link to shot.created deliveries.",
  );
});

test("deliveryLinkToastMessage: generic when nothing's active", () => {
  assert.equal(
    deliveryLinkToastMessage({ status: "all", event: "all" }),
    "Copied a link to this deliveries view.",
  );
});
