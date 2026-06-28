// Pure helper for the /webhooks "Recent deliveries" When column. The table
// prints a full absolute timestamp ("Jun 27, 19:00:05") which is precise but
// hard to scan when triaging a burst of recent attempts -- "was that one a
// minute ago or an hour ago?". This turns the stored ISO string into a
// glanceable relative phrase ("3m ago") rendered as a faint second line, with
// the absolute time kept as the hover title. Reuses the F59 relativeTime
// formatter so the bucket vocabulary ("just now" / "Nm ago" / "Nh ago") stays
// consistent with the command palette's recent-shots rows.
//
// Pure + DOM-free (takes an explicit `now` so tests are deterministic). Returns
// "" for a missing / unparseable timestamp so the caller renders no second
// line rather than "Invalid Date ago".

import { relativeTime } from "./relative-time";

// Format a delivery's created_at ISO string as a relative phrase against
// `now` (epoch ms). A null / blank / unparseable value yields "" so the row
// shows only its absolute time. A valid date delegates to relativeTime, which
// already collapses future + sub-minute gaps to "just now".
export function deliveryRelativeLabel(
  iso: string | null | undefined,
  now: number,
): string {
  if (typeof iso !== "string" || !iso.trim()) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  return relativeTime(t, now);
}
