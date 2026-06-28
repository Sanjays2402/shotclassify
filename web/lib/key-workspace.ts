// Workspace grouping + filtering for the /keys list (F137). A multi-tenant
// install issues keys per workspace, but the flat table interleaves them.
// This pure, DOM-free module derives the distinct workspaces (with counts),
// validates a selected workspace, and narrows a key list to one workspace,
// so the page can offer a removable workspace filter chip (mirroring the
// FilterBreadcrumb pattern) without scattering the bucketing logic in JSX.

// The slice of a key row this module needs. Mirrors KeyRow's optional field.
export type WorkspaceScoped = { workspace_id?: string | null };

// Keys whose workspace is unset (or literal "default") fall under this label.
export const DEFAULT_WORKSPACE = "default";

// Normalise a key's raw workspace to a stable bucket id. Blank / non-string /
// the literal "default" all collapse to DEFAULT_WORKSPACE so they group as one.
export function workspaceOf(k: WorkspaceScoped): string {
  const w = typeof k.workspace_id === "string" ? k.workspace_id.trim() : "";
  return w === "" ? DEFAULT_WORKSPACE : w;
}

export type WorkspaceCount = { workspace: string; count: number };

// Distinct workspaces present in the list with per-workspace key counts.
// Sorted "default" first, then alphabetical, so the chip row reads stably.
// Each workspace appears once even with many keys; an empty list -> [].
export function distinctWorkspaces(keys: WorkspaceScoped[]): WorkspaceCount[] {
  if (!Array.isArray(keys)) return [];
  const counts = new Map<string, number>();
  for (const k of keys) {
    const w = workspaceOf(k);
    counts.set(w, (counts.get(w) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([workspace, count]) => ({ workspace, count }))
    .sort((a, b) => {
      if (a.workspace === DEFAULT_WORKSPACE) return -1;
      if (b.workspace === DEFAULT_WORKSPACE) return 1;
      return a.workspace.localeCompare(b.workspace);
    });
}

// True when a workspace filter is worth offering: only multi-tenant installs
// (>= 2 distinct workspaces) benefit from the chip, so a single-workspace
// fleet stays uncluttered.
export function hasMultipleWorkspaces(keys: WorkspaceScoped[]): boolean {
  return distinctWorkspaces(keys).length > 1;
}

// Coerce a selected-workspace value (URL / state) into a present workspace, or
// null when blank / unknown -- so a stale selection can't hide every key.
export function parseWorkspaceFilter(
  raw: string | null | undefined,
  keys: WorkspaceScoped[],
): string | null {
  if (typeof raw !== "string") return null;
  const t = raw.trim();
  if (!t) return null;
  return distinctWorkspaces(keys).some((w) => w.workspace === t) ? t : null;
}

// Narrow the list to a single workspace; a null filter is a pass-through.
export function filterByWorkspace<T extends WorkspaceScoped>(
  keys: T[],
  workspace: string | null,
): T[] {
  if (!workspace) return Array.isArray(keys) ? keys : [];
  return (Array.isArray(keys) ? keys : []).filter(
    (k) => workspaceOf(k) === workspace,
  );
}

// Chip label for the active workspace breadcrumb -- "default" stays as-is.
export function workspaceChipLabel(workspace: string): string {
  return `ws: ${workspace}`;
}
