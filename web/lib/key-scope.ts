// Single source of truth for the API-key scope model on the /keys page
// (F130). The read/write/admin logic was copy-pasted across the page in three
// shapes that had quietly drifted:
//   * the create form mapped its <select> value to a scope array inline
//     ("admin" -> [read,write,admin], "write" -> [read,write], else [read]);
//   * the list badge re-derived a label / colour tier / hover title from a
//     key's scopes array inline;
//   * the <select> options hard-coded their own copy.
// Centralising it here -- pure, DOM-free -- means the hierarchy (admin implies
// write implies read), the human labels, and the descriptions can't disagree
// again, and each piece is unit-tested in one place. Mirrors the server-side
// normalizeScopes() in keystore-core.ts without importing it (that module
// pulls in node:fs and can't load in a client component).

export type KeyScope = "read" | "write" | "admin";

// The single choice the create form offers. A "tier" expands into the full
// implied scope array via scopesForSelection -- you never pick "read" AND
// "write" separately, you pick the highest tier you want.
export type ScopeTier = "read" | "write" | "admin";

// Catalogue backing the create <select> (option order = on-screen order) and
// any future scope picker. `value` is the stored tier; `label` is the option
// text; `summary` is the short badge word; `description` is the hover/help
// sentence. Keeping all four together is what stops the option copy and the
// badge title from drifting.
export const SCOPE_OPTIONS: {
  value: ScopeTier;
  label: string;
  summary: string;
  description: string;
}[] = [
  {
    value: "write",
    label: "Read and write (classify)",
    summary: "read+write",
    description: "Can call POST /v1/classify and all read endpoints.",
  },
  {
    value: "read",
    label: "Read only (list, fetch, usage)",
    summary: "read",
    description:
      "Read-only. POST /v1/classify will return 403 insufficient_scope.",
  },
  {
    value: "admin",
    label: "Admin (manage webhooks, full access)",
    summary: "admin",
    description:
      "Admin scope. Can manage webhooks plus all classify and read endpoints.",
  },
];

// Expand a chosen tier into the full implied scope array, applying the
// admin -> write -> read hierarchy so the wire payload matches what the
// server's normalizeScopes() would produce. An unknown value coerces to the
// safe read+write default (the historical fallback for legacy keys).
export function scopesForSelection(tier: ScopeTier | string): KeyScope[] {
  if (tier === "admin") return ["read", "write", "admin"];
  if (tier === "read") return ["read"];
  // "write" and anything unrecognised both land on the read+write default.
  return ["read", "write"];
}

// Reduce a key's stored scope array to the single tier word it should display.
// A missing / empty array is treated as the read+write legacy default (same
// rule the server uses when backfilling old keys). admin wins over write wins
// over read.
export function scopeTier(scopes: KeyScope[] | undefined | null): ScopeTier {
  const list = Array.isArray(scopes) && scopes.length > 0 ? scopes : ["read", "write"];
  if (list.includes("admin")) return "admin";
  if (list.includes("write")) return "write";
  return "read";
}

// The short badge label for a key's scopes ("admin" / "read+write" / "read").
export function scopeLabel(scopes: KeyScope[] | undefined | null): string {
  const tier = scopeTier(scopes);
  return SCOPE_OPTIONS.find((o) => o.value === tier)?.summary ?? "read";
}

// The hover/help sentence describing what a key's scopes permit. Reused as the
// badge `title` and as the create <select> help text.
export function scopeDescription(scopes: KeyScope[] | undefined | null): string {
  const tier = scopeTier(scopes);
  return (
    SCOPE_OPTIONS.find((o) => o.value === tier)?.description ??
    "Read-only. POST /v1/classify will return 403 insufficient_scope."
  );
}

// True when a key can call the write endpoints (write or admin). Drives the
// felt-green vs muted badge styling -- a write-capable key reads as "live".
export function scopeCanWrite(scopes: KeyScope[] | undefined | null): boolean {
  const tier = scopeTier(scopes);
  return tier === "write" || tier === "admin";
}
