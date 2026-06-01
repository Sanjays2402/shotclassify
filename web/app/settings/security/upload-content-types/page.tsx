"use client";

// Per-tenant allow-list of upload Content-Type values. Empty list keeps
// the legacy gate (any image/*). Non-empty list locks the classify
// surface to exactly the listed MIME types, blocking SVG, TIFF, HEIC,
// and anything else procurement does not want entering the pipeline.
// Tightening the policy takes effect on the very next upload.

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  ShieldCheck,
  Plus,
  Trash,
  FloppyDisk,
  Warning,
  CheckCircle,
  FileImage,
  Lock,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type PolicyResponse = {
  tenant_id: string;
  types: string[];
  enforced: boolean;
  max_entries: number;
  known: string[];
};

type ApiError = Error & { status?: number };

const MIME_RE = /^[a-z0-9][a-z0-9!#$&^_.+\-]{0,126}\/[a-z0-9][a-z0-9!#$&^_.+\-]{0,126}$/;

function isProbablyMime(s: string): boolean {
  const v = s.trim().toLowerCase().split(";")[0].trim();
  return MIME_RE.test(v);
}

export default function UploadContentTypesPage() {
  const { data, error, isLoading, mutate } = useSWR<PolicyResponse>(
    "/api/settings/security/upload-content-types",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [draft, setDraft] = useState<string[]>([]);
  const [newEntry, setNewEntry] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  useEffect(() => {
    if (data?.types) setDraft(data.types);
  }, [data?.types]);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const dirty = useMemo(() => {
    if (!data?.types) return draft.length > 0;
    if (data.types.length !== draft.length) return true;
    for (let i = 0; i < draft.length; i += 1) {
      if (data.types[i] !== draft[i]) return true;
    }
    return false;
  }, [data?.types, draft]);

  const max = data?.max_entries ?? 32;
  const known = data?.known ?? [];
  const atCap = draft.length >= max;

  function addEntry(raw: string) {
    const v = raw.trim().toLowerCase().split(";")[0].trim();
    if (!v) return;
    if (!isProbablyMime(v)) {
      setFlash({
        kind: "err",
        msg: "Enter a MIME type like image/png. Parameters are not stored.",
      });
      return;
    }
    if (draft.includes(v)) {
      setFlash({ kind: "err", msg: "Already in the list." });
      return;
    }
    if (atCap) {
      setFlash({ kind: "err", msg: `At most ${max} entries per workspace.` });
      return;
    }
    setDraft([...draft, v].sort());
    setNewEntry("");
    setFlash(null);
  }

  function remove(t: string) {
    setDraft(draft.filter((x) => x !== t));
  }

  async function save() {
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch(
        "/api/settings/security/upload-content-types",
        {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ types: draft }),
        },
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = body?.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : detail?.error ?? body?.error ?? `HTTP ${res.status}`;
        throw new Error(msg);
      }
      await mutate();
      setFlash({
        kind: "ok",
        msg: draft.length
          ? "Allow-list saved. The next upload outside this list is rejected with HTTP 415."
          : "Allow-list cleared. The classify route falls back to accepting any image/* MIME.",
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setFlash({ kind: "err", msg });
    } finally {
      setBusy(false);
    }
  }

  function revert() {
    setDraft(data?.types ?? []);
    setFlash(null);
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:py-10">
      <header className="mb-6 flex items-start gap-3">
        <ShieldCheck size={28} weight="duotone" className="mt-1 shrink-0" />
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Upload content type allow-list
          </h1>
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            Lock the classify pipeline to a specific set of MIME types for
            this workspace. When empty, any image/* MIME is accepted (legacy
            behaviour). When non-empty, every upload whose Content-Type is
            not on the list is rejected with HTTP 415 before the file is
            buffered or sent to the model.
          </p>
        </div>
      </header>

      {unauth && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <div className="flex items-center gap-2">
            <Lock size={16} weight="duotone" />
            <span>Sign in to manage security settings.</span>
          </div>
        </div>
      )}

      {forbidden && (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <div className="flex items-center gap-2">
            <Warning size={16} weight="duotone" />
            <span>
              You need the admin role to view or change the upload content
              type allow-list.
            </span>
          </div>
        </div>
      )}

      {!unauth && !forbidden && (
        <section className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-950 sm:p-6">
          {isLoading && !data ? (
            <div className="space-y-3" aria-busy="true" aria-live="polite">
              <div className="h-9 w-full animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
              <div className="h-9 w-full animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
              <div className="h-9 w-2/3 animate-pulse rounded-md bg-neutral-200 dark:bg-neutral-800" />
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-2 sm:flex-row">
                <div className="relative flex-1">
                  <FileImage
                    size={16}
                    weight="duotone"
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400"
                  />
                  <input
                    type="text"
                    inputMode="text"
                    spellCheck={false}
                    autoCapitalize="off"
                    autoCorrect="off"
                    value={newEntry}
                    onChange={(e) => setNewEntry(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addEntry(newEntry);
                      }
                    }}
                    placeholder="image/png"
                    aria-label="MIME type to add"
                    className="h-10 w-full rounded-md border border-neutral-300 bg-white pl-9 pr-3 text-sm outline-none transition focus:border-neutral-500 focus:ring-2 focus:ring-neutral-300 dark:border-neutral-700 dark:bg-neutral-900 dark:focus:border-neutral-500 dark:focus:ring-neutral-700"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => addEntry(newEntry)}
                  disabled={!newEntry.trim() || atCap}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-neutral-900 px-4 text-sm font-medium text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
                >
                  <Plus size={16} weight="bold" />
                  Add
                </button>
              </div>

              <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
                {draft.length} of {max} entries used.{" "}
                {data?.enforced
                  ? "Policy is enforced for this workspace."
                  : "Policy is not enforced; legacy image/* gate is active."}
              </p>

              {known.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {known
                    .filter((t) => !draft.includes(t))
                    .map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => addEntry(t)}
                        disabled={atCap}
                        className="inline-flex items-center gap-1 rounded-full border border-neutral-300 bg-neutral-50 px-2.5 py-1 text-[11px] font-mono text-neutral-700 transition hover:border-neutral-400 hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
                      >
                        <Plus size={11} weight="bold" />
                        {t}
                      </button>
                    ))}
                </div>
              )}

              <ul className="mt-4 divide-y divide-neutral-200 rounded-md border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
                {draft.length === 0 ? (
                  <li className="px-4 py-6 text-center text-sm text-neutral-500 dark:text-neutral-400">
                    No entries. Any image/* MIME is accepted.
                  </li>
                ) : (
                  draft.map((t) => (
                    <li
                      key={t}
                      className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm"
                    >
                      <span className="break-all font-mono text-[13px]">{t}</span>
                      <button
                        type="button"
                        onClick={() => remove(t)}
                        aria-label={`Remove ${t}`}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-neutral-500 transition hover:bg-red-50 hover:text-red-700 dark:hover:bg-red-950 dark:hover:text-red-300"
                      >
                        <Trash size={16} weight="duotone" />
                      </button>
                    </li>
                  ))
                )}
              </ul>

              <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end">
                {dirty && (
                  <button
                    type="button"
                    onClick={revert}
                    disabled={busy}
                    className="h-10 rounded-md border border-neutral-300 px-4 text-sm font-medium transition hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
                  >
                    Revert
                  </button>
                )}
                <button
                  type="button"
                  onClick={save}
                  disabled={!dirty || busy}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-neutral-900 px-4 text-sm font-medium text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
                >
                  <FloppyDisk size={16} weight="duotone" />
                  {busy ? "Saving" : "Save allow-list"}
                </button>
              </div>

              {flash && (
                <div
                  role="status"
                  className={`mt-4 flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
                    flash.kind === "ok"
                      ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
                      : "border-red-300 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
                  }`}
                >
                  {flash.kind === "ok" ? (
                    <CheckCircle size={16} weight="duotone" className="mt-0.5 shrink-0" />
                  ) : (
                    <Warning size={16} weight="duotone" className="mt-0.5 shrink-0" />
                  )}
                  <span>{flash.msg}</span>
                </div>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
}
