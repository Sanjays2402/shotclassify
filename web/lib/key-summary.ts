// Fleet summary for the /keys list header (F133). The "Your keys" section
// header showed only a bare "N keys" count. When you're managing more than a
// couple of credentials, the useful at-a-glance facts are how many are
// actually live vs dormant vs never-used (a security-hygiene signal) and the
// total call volume across all of them. This pure, DOM-free reducer rolls a
// key list into those counts, reusing the SAME keyUsageStatus buckets the
// per-row pills use (F131) so the header total and the row badges can never
// disagree.

import { keyUsageStatus, type KeyActivityStatus } from "./key-activity";

type SummaryInput = {
  last_used_at?: string | null;
  usage_count?: number | null;
};

export type KeysSummary = {
  total: number;
  active: number;
  idle: number;
  unused: number;
  totalCalls: number;
};

// Reduce a key list into the header summary against `now` (epoch ms). Each key
// is bucketed by keyUsageStatus so the active/idle/unused split matches the
// row pills exactly. usage_count is summed defensively (non-finite / negative
// counts contribute 0). A non-array input yields an all-zero summary.
export function summarizeKeys(
  keys: readonly SummaryInput[] | null | undefined,
  now: number,
): KeysSummary {
  const out: KeysSummary = { total: 0, active: 0, idle: 0, unused: 0, totalCalls: 0 };
  if (!Array.isArray(keys)) return out;
  for (const k of keys) {
    if (!k || typeof k !== "object") continue;
    out.total += 1;
    const status: KeyActivityStatus = keyUsageStatus(k, now);
    if (status === "active") out.active += 1;
    else if (status === "idle") out.idle += 1;
    else out.unused += 1;
    const calls = Number(k.usage_count);
    if (Number.isFinite(calls) && calls > 0) out.totalCalls += Math.trunc(calls);
  }
  return out;
}

// The compact header chips to render, in display order. Only the non-zero
// exceptional buckets (idle / unused) produce a chip -- a healthy all-active
// fleet shows just the total + call volume, keeping the header quiet. The
// `tone` lets the component pick a colour without re-deriving meaning. Returns
// [] for an empty fleet so the caller can hide the strip entirely.
export type KeysSummaryChip = {
  key: "total" | "calls" | "idle" | "unused";
  label: string;
  tone: "neutral" | "warn" | "mute";
  hint: string;
};

export function keysSummaryChips(summary: KeysSummary): KeysSummaryChip[] {
  if (!summary || summary.total <= 0) return [];
  const chips: KeysSummaryChip[] = [
    {
      key: "total",
      label: `${summary.total} ${summary.total === 1 ? "key" : "keys"}`,
      tone: "neutral",
      hint: "Total keys in this workspace.",
    },
  ];
  if (summary.totalCalls > 0) {
    chips.push({
      key: "calls",
      label: `${summary.totalCalls.toLocaleString()} ${summary.totalCalls === 1 ? "call" : "calls"}`,
      tone: "neutral",
      hint: "Total authenticated requests across all keys.",
    });
  }
  if (summary.idle > 0) {
    chips.push({
      key: "idle",
      label: `${summary.idle} idle`,
      tone: "warn",
      hint: "Keys not used in over 30 days. Consider rotating or revoking them.",
    });
  }
  if (summary.unused > 0) {
    chips.push({
      key: "unused",
      label: `${summary.unused} never used`,
      tone: "mute",
      hint: "Keys that have never authenticated a request.",
    });
  }
  return chips;
}

// The two chips that can drive a table filter (F144): idle + never-used map
// to keyUsageStatus buckets. total + calls are facts, not filters. A chip
// click toggles its bucket; nothing else narrows the list.
export type KeySummaryFilter = "idle" | "unused" | null;

export function chipIsFilterable(key: KeysSummaryChip["key"]): boolean {
  return key === "idle" || key === "unused";
}

// Toggle the active filter from a chip click: clicking the armed chip clears
// it, any other filterable chip switches to it, non-filter chips are no-ops.
export function toggleSummaryFilter(
  current: KeySummaryFilter,
  key: KeysSummaryChip["key"],
): KeySummaryFilter {
  if (!chipIsFilterable(key)) return current;
  const next = key as "idle" | "unused";
  return current === next ? null : next;
}

// Narrow a key list to the active status filter, reusing the exact
// keyUsageStatus buckets the chips counted. null returns the list unchanged.
export function filterKeysByStatus<T extends SummaryInput>(
  keys: readonly T[] | null | undefined,
  filter: KeySummaryFilter,
  now: number,
): T[] {
  if (!Array.isArray(keys)) return [];
  if (filter === null) return keys.slice();
  return keys.filter((k) => k && typeof k === "object" && keyUsageStatus(k, now) === filter);
}
