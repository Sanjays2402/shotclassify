// Pure helpers for /v1 routes. Kept Next-free so they can be unit-tested.
export const SHOT_LIST_ALLOWED = new Set([
  "limit",
  "offset",
  "category",
  "since",
  "until",
  "min_confidence",
  "q",
  "tag",
  "sort",
]);

export const SHOT_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

export type FilteredQuery = {
  ok: true;
  params: URLSearchParams;
} | {
  ok: false;
  code: string;
  message: string;
};

/**
 * Filters an incoming query string down to the allowed list, validates limit,
 * caps it at 200, and defaults to 50 when omitted.
 */
export function filterShotListQuery(input: URLSearchParams): FilteredQuery {
  const out = new URLSearchParams();
  for (const [k, v] of input) {
    if (SHOT_LIST_ALLOWED.has(k)) out.set(k, v);
  }
  const limitRaw = out.get("limit");
  if (limitRaw !== null) {
    const n = Number(limitRaw);
    if (!Number.isFinite(n) || n <= 0) {
      return {
        ok: false,
        code: "invalid_limit",
        message: "limit must be a positive integer.",
      };
    }
    out.set("limit", String(Math.min(Math.floor(n), 200)));
  } else {
    out.set("limit", "50");
  }
  return { ok: true, params: out };
}

export function isValidShotId(id: string): boolean {
  return SHOT_ID_RE.test(id);
}
