// Activity helpers for the /keys list (F131). The "Last used" column shows a
// precise absolute timestamp ("Jun 27, 19:00") which is exact but hard to scan
// when you're auditing a fleet of keys -- "is this one stale? was it ever
// used?". This adds two glanceable signals derived from a key's last_used_at /
// usage_count:
//   * keyRelativeLabel -- the same "3d ago" phrasing the rest of the app uses
//     (delegates to F59 relativeTime) for a faint second line under the date.
//   * keyUsageStatus   -- a coarse unused / idle / active triage bucket so a
//     never-called or long-dormant key reads at a glance and can be styled.
//
// Pure + DOM-free: every function takes an explicit `now` (epoch ms) so the
// buckets are deterministic in tests. Mirrors lib/delivery-when.ts.

import { relativeTime } from "./relative-time";

// A key is "idle" once this long has passed since its last use. 30 days is the
// same dormancy window security reviews tend to flag -- long enough that a
// weekly cron still reads as active, short enough to surface a forgotten key.
export const KEY_IDLE_AFTER_MS = 30 * 24 * 60 * 60 * 1000;

export type KeyActivityStatus = "unused" | "idle" | "active";

type ActivityInput = {
  last_used_at?: string | null;
  usage_count?: number | null;
};

// Format a key's last_used_at as a relative phrase against `now`. A null /
// blank / unparseable value yields "" so the row renders no second line (the
// absolute column already shows "never"). A valid date delegates to
// relativeTime, which collapses future + sub-minute gaps to "just now".
export function keyRelativeLabel(
  iso: string | null | undefined,
  now: number,
): string {
  if (typeof iso !== "string" || !iso.trim()) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  return relativeTime(t, now);
}

// Triage a key into one of three buckets:
//   * "unused" -- never called (no last_used_at, or a zero/absent usage_count
//                 with no timestamp). The clearest "you can probably revoke
//                 this" signal.
//   * "idle"   -- last used more than KEY_IDLE_AFTER_MS ago (dormant).
//   * "active" -- used within the idle window.
// An unparseable timestamp is treated as unused rather than throwing, so a
// corrupt record degrades to the most conservative label.
export function keyUsageStatus(
  key: ActivityInput,
  now: number,
): KeyActivityStatus {
  const iso = key.last_used_at;
  const used = typeof iso === "string" && iso.trim().length > 0;
  if (!used) return "unused";
  const t = Date.parse(iso as string);
  if (!Number.isFinite(t)) return "unused";
  // A future timestamp (clock skew) counts as active -- it was clearly used.
  if (!Number.isFinite(now)) return "active";
  return now - t > KEY_IDLE_AFTER_MS ? "idle" : "active";
}

// Short badge word for a status, or null for "active" (the healthy default
// needs no chip -- only the exceptional unused / idle states get a pill, so
// the column stays quiet for the common case).
export function keyStatusLabel(status: KeyActivityStatus): string | null {
  if (status === "unused") return "never used";
  if (status === "idle") return "idle";
  return null;
}

// Longer hover sentence describing what a status means + why it's worth
// noticing, used as the pill `title`.
export function keyStatusHint(status: KeyActivityStatus): string {
  if (status === "unused") {
    return "This key has never authenticated a request. If you don't need it, revoke it.";
  }
  if (status === "idle") {
    return "This key hasn't been used in over 30 days. Consider rotating or revoking it.";
  }
  return "Used recently.";
}
