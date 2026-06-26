// Pure tests for the /shots deep-link query parser (F30). No DOM.
import test from "node:test";
import assert from "node:assert/strict";

import {
  parseShotsDeepLink,
  hasDeepLink,
  buildShotsQuery,
  buildShotsDeepLink,
  type ParamSource,
  type ShotsFilterState,
} from "./shots-deeplink.ts";

// Tiny ParamSource over a plain record -- stands in for URLSearchParams.
function src(params: Record<string, string>): ParamSource {
  return { get: (name: string) => (name in params ? params[name] : null) };
}

test("parseShotsDeepLink: a valid category passes through", () => {
  assert.equal(parseShotsDeepLink(src({ category: "receipt" })).category, "receipt");
  assert.equal(
    parseShotsDeepLink(src({ category: "  code_snippet  " })).category,
    "code_snippet",
  );
});

test("parseShotsDeepLink: an unknown category is dropped", () => {
  assert.equal(parseShotsDeepLink(src({ category: "spaceship" })).category, undefined);
  assert.equal(parseShotsDeepLink(src({ category: "" })).category, undefined);
});

test("parseShotsDeepLink: pinned accepts true/1/yes/on, rejects others", () => {
  for (const v of ["true", "1", "yes", "on", "TRUE", "On"]) {
    assert.equal(parseShotsDeepLink(src({ pinned: v })).pinnedOnly, true, v);
  }
  for (const v of ["false", "0", "no", "", "maybe"]) {
    assert.equal(parseShotsDeepLink(src({ pinned: v })).pinnedOnly, undefined, v);
  }
});

test("parseShotsDeepLink: min_conf as a whole percent clamps to 0..100", () => {
  assert.equal(parseShotsDeepLink(src({ min_conf: "80" })).minConfPct, 80);
  assert.equal(parseShotsDeepLink(src({ min_conf: "150" })).minConfPct, 100);
  // A 0 floor is the inert default -> omitted, not stored as 0.
  assert.equal(parseShotsDeepLink(src({ min_conf: "0" })).minConfPct, undefined);
});

test("parseShotsDeepLink: min_conf as a 0..1 fraction is upscaled to percent", () => {
  assert.equal(parseShotsDeepLink(src({ min_conf: "0.8" })).minConfPct, 80);
  assert.equal(parseShotsDeepLink(src({ min_conf: "1" })).minConfPct, 100);
});

test("parseShotsDeepLink: min_conf junk is dropped", () => {
  assert.equal(parseShotsDeepLink(src({ min_conf: "abc" })).minConfPct, undefined);
});

test("parseShotsDeepLink: dates must be yyyy-mm-dd shaped", () => {
  const ok = parseShotsDeepLink(src({ since: "2026-01-01", until: "2026-02-15" }));
  assert.equal(ok.since, "2026-01-01");
  assert.equal(ok.until, "2026-02-15");
  const bad = parseShotsDeepLink(src({ since: "01/01/2026", until: "yesterday" }));
  assert.equal(bad.since, undefined);
  assert.equal(bad.until, undefined);
});

test("parseShotsDeepLink: only known sort values pass", () => {
  assert.equal(parseShotsDeepLink(src({ sort: "conf_desc" })).sort, "conf_desc");
  assert.equal(parseShotsDeepLink(src({ sort: "new" })).sort, "new");
  assert.equal(parseShotsDeepLink(src({ sort: "random" })).sort, undefined);
});

test("parseShotsDeepLink: q and tag are trimmed; tag is lowercased + capped", () => {
  assert.equal(parseShotsDeepLink(src({ q: "  invoice  " })).q, "invoice");
  assert.equal(parseShotsDeepLink(src({ tag: "  URGENT  " })).tag, "urgent");
  const long = "x".repeat(50);
  assert.equal(parseShotsDeepLink(src({ tag: long })).tag!.length, 32);
});

test("parseShotsDeepLink: combined params build a full slice", () => {
  const link = parseShotsDeepLink(
    src({ category: "chart", pinned: "true", min_conf: "90", sort: "old" }),
  );
  assert.deepEqual(link, {
    category: "chart",
    pinnedOnly: true,
    minConfPct: 90,
    sort: "old",
  });
});

test("parseShotsDeepLink: null / shapeless source yields an empty slice", () => {
  assert.deepEqual(parseShotsDeepLink(null), {});
  assert.deepEqual(parseShotsDeepLink(undefined), {});
  assert.deepEqual(parseShotsDeepLink({} as ParamSource), {});
});

test("hasDeepLink: true only when at least one filter is seeded", () => {
  assert.equal(hasDeepLink({}), false);
  assert.equal(hasDeepLink({ category: "receipt" }), true);
  assert.equal(hasDeepLink({ pinnedOnly: true }), true);
});

test("parseShotsDeepLink: works against a real URLSearchParams", () => {
  const usp = new URLSearchParams("category=receipt&pinned=1&min_conf=75");
  const link = parseShotsDeepLink(usp);
  assert.equal(link.category, "receipt");
  assert.equal(link.pinnedOnly, true);
  assert.equal(link.minConfPct, 75);
});

// --- F47: the inverse builder ---------------------------------------------

test("buildShotsQuery: empty / all-default state yields an empty string", () => {
  assert.equal(buildShotsQuery({}), "");
  assert.equal(
    buildShotsQuery({
      category: "",
      q: "",
      tag: "",
      minConfPct: 0,
      since: "",
      until: "",
      sort: "new", // the inert default
      pinnedOnly: false,
    }),
    "",
  );
});

test("buildShotsQuery: only active filters are emitted", () => {
  const usp = new URLSearchParams(
    buildShotsQuery({ category: "receipt", pinnedOnly: true, minConfPct: 90 }),
  );
  assert.equal(usp.get("category"), "receipt");
  assert.equal(usp.get("pinned"), "true");
  assert.equal(usp.get("min_conf"), "90");
  assert.equal(usp.get("q"), null);
  assert.equal(usp.get("sort"), null);
});

test("buildShotsQuery: an unknown category is dropped", () => {
  assert.equal(buildShotsQuery({ category: "spaceship" as never }), "");
});

test("buildShotsQuery: the inert sort default is omitted, others kept", () => {
  assert.equal(buildShotsQuery({ sort: "new" }), "");
  assert.equal(
    new URLSearchParams(buildShotsQuery({ sort: "conf_desc" })).get("sort"),
    "conf_desc",
  );
});

test("buildShotsQuery: a 0 conf floor is omitted; >0 clamps to 0..100", () => {
  assert.equal(buildShotsQuery({ minConfPct: 0 }), "");
  assert.equal(
    new URLSearchParams(buildShotsQuery({ minConfPct: 150 })).get("min_conf"),
    "100",
  );
  assert.equal(
    new URLSearchParams(buildShotsQuery({ minConfPct: 55 })).get("min_conf"),
    "55",
  );
});

test("buildShotsQuery: tag is lowercased + capped like the parser", () => {
  const usp = new URLSearchParams(buildShotsQuery({ tag: "  URGENT  " }));
  assert.equal(usp.get("tag"), "urgent");
  const long = "x".repeat(50);
  assert.equal(
    new URLSearchParams(buildShotsQuery({ tag: long })).get("tag")!.length,
    32,
  );
});

test("buildShotsQuery: malformed dates are dropped", () => {
  assert.equal(buildShotsQuery({ since: "01/02/2026", until: "soon" }), "");
  const usp = new URLSearchParams(
    buildShotsQuery({ since: "2026-01-01", until: "2026-02-15" }),
  );
  assert.equal(usp.get("since"), "2026-01-01");
  assert.equal(usp.get("until"), "2026-02-15");
});

test("buildShotsDeepLink: bare base when no filter is active", () => {
  assert.equal(buildShotsDeepLink({}), "/shots");
  assert.equal(buildShotsDeepLink({}, "https://x.app/shots"), "https://x.app/shots");
});

test("buildShotsDeepLink: appends the query when filters are active", () => {
  const url = buildShotsDeepLink(
    { category: "chart", pinnedOnly: true },
    "https://x.app/shots",
  );
  assert.ok(url.startsWith("https://x.app/shots?"));
  const usp = new URL(url).searchParams;
  assert.equal(usp.get("category"), "chart");
  assert.equal(usp.get("pinned"), "true");
});

test("F47 round trip: parse(build(state)) is stable", () => {
  const state: ShotsFilterState = {
    category: "chat_screenshot",
    q: "invoice",
    tag: "urgent",
    minConfPct: 80,
    since: "2026-01-01",
    until: "2026-02-15",
    sort: "conf_asc",
    pinnedOnly: true,
  };
  const link = parseShotsDeepLink(new URLSearchParams(buildShotsQuery(state)));
  assert.deepEqual(link, {
    category: "chat_screenshot",
    q: "invoice",
    tag: "urgent",
    minConfPct: 80,
    since: "2026-01-01",
    until: "2026-02-15",
    sort: "conf_asc",
    pinnedOnly: true,
  });
});
