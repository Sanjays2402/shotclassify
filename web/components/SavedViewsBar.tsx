"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import {
  BookmarkSimple,
  FloppyDisk,
  Trash,
  Plus,
  X,
  Spinner,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher, ENDPOINTS } from "@/lib/api";
import type { Category } from "@/lib/categories";

export type SavedViewFilters = {
  category?: string;
  q?: string;
  since?: string;
  until?: string;
  min_conf?: number;
  sort?: "new" | "old" | "conf_desc" | "conf_asc";
  tag?: string;
  limit?: number;
};

export type SavedView = {
  id: string;
  name: string;
  filters: SavedViewFilters;
  created_at?: string;
  updated_at?: string;
};

type Props = {
  current: SavedViewFilters;
  onApply: (filters: SavedViewFilters) => void;
};

function summarize(f: SavedViewFilters): string {
  const bits: string[] = [];
  if (f.category) bits.push(f.category);
  if (f.q) bits.push(`"${f.q}"`);
  if (f.tag) bits.push(`#${f.tag}`);
  if (typeof f.min_conf === "number" && f.min_conf > 0)
    bits.push(`>=${Math.round(f.min_conf * 100)}%`);
  if (f.since || f.until)
    bits.push(`${f.since || "..."} to ${f.until || "..."}`);
  if (f.sort && f.sort !== "new") bits.push(f.sort);
  return bits.join(" • ") || "no filters";
}

export function SavedViewsBar({ current, onApply }: Props) {
  const { mutate } = useSWRConfig();
  const { data, error, isLoading } = useSWR<{
    items: SavedView[];
    count: number;
  }>(ENDPOINTS.savedViews, fetcher);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const items = data?.items ?? [];

  async function handleSave() {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      const r = await fetch(ENDPOINTS.savedViews, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: trimmed, filters: current }),
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        setFlash(t || `Save failed (${r.status})`);
      } else {
        setName("");
        setOpen(false);
        await mutate(ENDPOINTS.savedViews);
        setFlash("Saved");
      }
    } catch (e: any) {
      setFlash(e?.message || "Save failed");
    } finally {
      setBusy(false);
      setTimeout(() => setFlash(null), 2500);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this saved view?")) return;
    const r = await fetch(ENDPOINTS.savedView(id), { method: "DELETE" });
    if (r.ok) {
      if (activeId === id) setActiveId(null);
      await mutate(ENDPOINTS.savedViews);
    }
  }

  function handleApply(v: SavedView) {
    setActiveId(v.id);
    onApply(v.filters || {});
  }

  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-md border border-zinc-200 bg-white/60 px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-900/40"
      data-testid="saved-views-bar"
    >
      <BookmarkSimple
        weight="duotone"
        className="h-4 w-4 text-zinc-500"
        aria-hidden
      />
      <span className="font-medium text-zinc-700 dark:text-zinc-200">
        Saved views
      </span>

      {error && (
        <span className="text-xs text-rose-600 dark:text-rose-400">
          Could not load
        </span>
      )}

      {isLoading && !data && (
        <Spinner
          className="h-4 w-4 animate-spin text-zinc-400"
          aria-label="Loading"
        />
      )}

      {!isLoading && items.length === 0 && (
        <span className="text-xs text-zinc-500">
          None yet. Set filters, then save the combo.
        </span>
      )}

      <div
        className="flex max-w-full flex-wrap items-center gap-1.5 overflow-x-auto"
        role="list"
      >
        {items.map((v) => {
          const active = v.id === activeId;
          return (
            <div
              key={v.id}
              role="listitem"
              className={
                "group flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition " +
                (active
                  ? "border-indigo-400 bg-indigo-50 text-indigo-900 dark:border-indigo-500/60 dark:bg-indigo-500/15 dark:text-indigo-100"
                  : "border-zinc-200 bg-zinc-50 text-zinc-700 hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:border-zinc-700")
              }
            >
              <button
                type="button"
                onClick={() => handleApply(v)}
                title={summarize(v.filters || {})}
                className="max-w-[14rem] truncate focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
              >
                {v.name}
              </button>
              <button
                type="button"
                onClick={() => handleDelete(v.id)}
                className="rounded-full p-0.5 text-zinc-400 opacity-0 transition hover:bg-rose-100 hover:text-rose-600 group-hover:opacity-100 focus:opacity-100 dark:hover:bg-rose-500/15"
                aria-label={`Delete saved view ${v.name}`}
              >
                <Trash weight="duotone" className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>

      <div className="ml-auto flex items-center gap-2">
        {flash && (
          <span className="text-xs text-zinc-500" aria-live="polite">
            {flash}
          </span>
        )}
        {!open ? (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-1 rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs font-medium text-zinc-700 hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200"
          >
            <Plus weight="duotone" className="h-3.5 w-3.5" />
            Save current
          </button>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSave();
            }}
            className="flex items-center gap-1"
          >
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="View name"
              maxLength={128}
              className="w-40 rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-900 outline-none focus:border-indigo-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              aria-label="Saved view name"
            />
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? (
                <Spinner className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <FloppyDisk weight="duotone" className="h-3.5 w-3.5" />
              )}
              Save
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setName("");
              }}
              className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              aria-label="Cancel"
            >
              <X weight="bold" className="h-3.5 w-3.5" />
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
