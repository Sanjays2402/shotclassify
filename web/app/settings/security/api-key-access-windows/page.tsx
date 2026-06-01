"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  Clock,
  Key as KeyIcon,
  CheckCircle,
  Warning,
  Plus,
  Trash,
  FloppyDisk,
  LockOpen,
  Globe,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

// One window allows traffic during [start, end) on the listed weekdays
// in a named IANA zone. Mon=0..Sun=6.
type AccessWindow = {
  weekdays: number[];
  start: string;
  end: string;
  tz: string;
};

type KeyRow = {
  id: string;
  label: string;
  tenant_id: string | null;
  owner_email: string | null;
  active: boolean;
  revoked_at: string | null;
  access_windows: AccessWindow[];
};

type KeysResponse = {
  keys: KeyRow[];
  tenant_id: string | null;
};

type ApiError = Error & { status?: number };

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const COMMON_TZS = [
  "UTC",
  "America/Los_Angeles",
  "America/New_York",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Australia/Sydney",
];

function summarise(windows: AccessWindow[]): string {
  if (!windows || windows.length === 0) return "Always allowed";
  return windows
    .map((w) => {
      const days = (w.weekdays || [])
        .slice()
        .sort((a, b) => a - b)
        .map((d) => WEEKDAY_LABELS[d] ?? `?${d}`)
        .join(" ");
      return `${days} ${w.start}-${w.end} ${w.tz}`;
    })
    .join("  •  ");
}

function isValidHHMM(s: string): boolean {
  return /^([01]\d|2[0-3]):([0-5]\d)$/.test(s);
}

export default function ApiKeyAccessWindowsPage() {
  const { data, error, isLoading, mutate } = useSWR<KeysResponse>(
    "/api/settings/security/api-key-access-windows",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<AccessWindow[]>([]);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<
    { kind: "ok" | "err"; msg: string } | null
  >(null);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const keys = useMemo(() => {
    if (!data?.keys) return [];
    return data.keys.filter((k) => k.revoked_at === null);
  }, [data]);

  const startEdit = (k: KeyRow) => {
    setEditingId(k.id);
    setDraft(
      (k.access_windows || []).map((w) => ({
        weekdays: [...w.weekdays],
        start: w.start,
        end: w.end,
        tz: w.tz,
      })),
    );
    setFlash(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraft([]);
    setOtp("");
  };

  const addWindow = () => {
    setDraft((d) => [
      ...d,
      { weekdays: [0, 1, 2, 3, 4], start: "09:00", end: "17:00", tz: "UTC" },
    ]);
  };

  const removeWindow = (idx: number) => {
    setDraft((d) => d.filter((_, i) => i !== idx));
  };

  const updateWindow = (idx: number, patch: Partial<AccessWindow>) => {
    setDraft((d) => d.map((w, i) => (i === idx ? { ...w, ...patch } : w)));
  };

  const toggleWeekday = (idx: number, day: number) => {
    setDraft((d) =>
      d.map((w, i) => {
        if (i !== idx) return w;
        const has = w.weekdays.includes(day);
        const next = has
          ? w.weekdays.filter((x) => x !== day)
          : [...w.weekdays, day].sort((a, b) => a - b);
        return { ...w, weekdays: next };
      }),
    );
  };

  const validateDraft = (): string | null => {
    for (const [i, w] of draft.entries()) {
      if (!w.weekdays || w.weekdays.length === 0) {
        return `Window ${i + 1}: pick at least one day.`;
      }
      if (!isValidHHMM(w.start) || !isValidHHMM(w.end)) {
        return `Window ${i + 1}: times must be HH:MM.`;
      }
      const toMin = (s: string) => {
        const [h, m] = s.split(":").map(Number);
        return h * 60 + m;
      };
      if (toMin(w.end) <= toMin(w.start)) {
        return `Window ${i + 1}: end must be after start (no overnight wrap; add a second window).`;
      }
      if (!w.tz) return `Window ${i + 1}: timezone is required.`;
    }
    return null;
  };

  const save = async (id: string) => {
    const v = validateDraft();
    if (v) {
      setFlash({ kind: "err", msg: v });
      return;
    }
    setBusy(true);
    setFlash(null);
    try {
      const headers: Record<string, string> = {
        "content-type": "application/json",
      };
      if (otp.trim()) headers["x-mfa-otp"] = otp.trim();
      const res = await fetch(
        `/api/settings/security/api-key-access-windows/${encodeURIComponent(id)}`,
        {
          method: "PATCH",
          headers,
          body: JSON.stringify({ access_windows: draft }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body?.detail || body?.error || res.statusText;
        throw new Error(
          typeof detail === "string" ? detail : JSON.stringify(detail),
        );
      }
      await mutate();
      cancelEdit();
      setFlash({ kind: "ok", msg: "Access windows saved." });
    } catch (e) {
      setFlash({
        kind: "err",
        msg: e instanceof Error ? e.message : "Save failed.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-4xl px-4 py-8 sm:py-12">
      <header className="mb-8">
        <div className="flex items-center gap-3">
          <Clock size={28} weight="duotone" className="text-zinc-700" />
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">
            API key access windows
          </h1>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-zinc-600">
          Restrict an API key to specific weekdays and hours in a named
          timezone. Requests outside every window are rejected at the auth
          boundary with HTTP 403. Leave a key unrestricted for always-on
          integrations.
        </p>
      </header>

      {flash && (
        <div
          role="status"
          className={`mb-6 flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
            flash.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-rose-200 bg-rose-50 text-rose-900"
          }`}
        >
          {flash.kind === "ok" ? (
            <CheckCircle size={16} weight="duotone" className="mt-0.5" />
          ) : (
            <Warning size={16} weight="duotone" className="mt-0.5" />
          )}
          <span>{flash.msg}</span>
        </div>
      )}

      {isLoading && (
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-lg border border-zinc-200 bg-zinc-50"
            />
          ))}
        </div>
      )}

      {unauth && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Sign in as a workspace admin to manage API key access windows.
        </div>
      )}
      {forbidden && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
          Your role does not allow managing API keys.
        </div>
      )}

      {!isLoading && !error && keys.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-4 py-12 text-center">
          <KeyIcon size={28} weight="duotone" className="text-zinc-400" />
          <p className="text-sm text-zinc-700">No active API keys yet.</p>
          <p className="text-xs text-zinc-500">
            Mint a key from Settings to manage its access window here.
          </p>
        </div>
      )}

      <ul className="space-y-3">
        {keys.map((k) => {
          const isEditing = editingId === k.id;
          const summary = summarise(k.access_windows);
          const restricted = (k.access_windows || []).length > 0;
          return (
            <li
              key={k.id}
              className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm"
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <KeyIcon
                      size={16}
                      weight="duotone"
                      className="text-zinc-500"
                    />
                    <span className="truncate font-medium text-zinc-900">
                      {k.label}
                    </span>
                    {restricted ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-800">
                        <Clock size={12} weight="duotone" />
                        Windowed
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs text-zinc-600">
                        <LockOpen size={12} weight="duotone" />
                        Always allowed
                      </span>
                    )}
                  </div>
                  <p className="mt-1 font-mono text-xs text-zinc-500">
                    {k.id}
                  </p>
                  <p className="mt-1 text-sm text-zinc-700">{summary}</p>
                  {k.owner_email && (
                    <p className="mt-1 text-xs text-zinc-500">
                      Owner: {k.owner_email}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 gap-2">
                  {!isEditing ? (
                    <button
                      type="button"
                      onClick={() => startEdit(k)}
                      className="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-800 shadow-sm hover:bg-zinc-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400"
                    >
                      Edit windows
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-700 shadow-sm hover:bg-zinc-50"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>

              {isEditing && (
                <div className="mt-4 space-y-3 border-t border-zinc-100 pt-4">
                  {draft.length === 0 && (
                    <p className="text-sm text-zinc-600">
                      No windows. Saving an empty list clears the restriction
                      so the key is accepted at any time.
                    </p>
                  )}
                  {draft.map((w, idx) => (
                    <div
                      key={idx}
                      className="rounded-md border border-zinc-200 bg-zinc-50 p-3"
                    >
                      <div className="flex flex-wrap items-center gap-1">
                        {WEEKDAY_LABELS.map((label, d) => {
                          const on = w.weekdays.includes(d);
                          return (
                            <button
                              key={label}
                              type="button"
                              onClick={() => toggleWeekday(idx, d)}
                              aria-pressed={on}
                              className={`rounded-md border px-2 py-1 text-xs ${
                                on
                                  ? "border-zinc-900 bg-zinc-900 text-white"
                                  : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-100"
                              }`}
                            >
                              {label}
                            </button>
                          );
                        })}
                      </div>
                      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
                        <label className="flex flex-col gap-1 text-xs text-zinc-600">
                          Start (24h)
                          <input
                            type="time"
                            value={w.start}
                            onChange={(e) =>
                              updateWindow(idx, { start: e.target.value })
                            }
                            className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none"
                          />
                        </label>
                        <label className="flex flex-col gap-1 text-xs text-zinc-600">
                          End (24h)
                          <input
                            type="time"
                            value={w.end}
                            onChange={(e) =>
                              updateWindow(idx, { end: e.target.value })
                            }
                            className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none"
                          />
                        </label>
                        <label className="flex flex-col gap-1 text-xs text-zinc-600">
                          Timezone
                          <div className="flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-2">
                            <Globe
                              size={14}
                              weight="duotone"
                              className="text-zinc-500"
                            />
                            <input
                              type="text"
                              list={`tz-options-${idx}`}
                              value={w.tz}
                              onChange={(e) =>
                                updateWindow(idx, { tz: e.target.value })
                              }
                              className="w-full bg-transparent py-1.5 text-sm text-zinc-900 focus:outline-none"
                              placeholder="UTC"
                            />
                            <datalist id={`tz-options-${idx}`}>
                              {COMMON_TZS.map((tz) => (
                                <option key={tz} value={tz} />
                              ))}
                            </datalist>
                          </div>
                        </label>
                      </div>
                      <div className="mt-3 flex justify-end">
                        <button
                          type="button"
                          onClick={() => removeWindow(idx)}
                          className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-white px-2 py-1 text-xs text-rose-700 hover:bg-rose-50"
                        >
                          <Trash size={12} weight="duotone" /> Remove window
                        </button>
                      </div>
                    </div>
                  ))}

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={addWindow}
                      className="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-800 hover:bg-zinc-50"
                    >
                      <Plus size={14} weight="duotone" /> Add window
                    </button>
                  </div>

                  <label className="flex flex-col gap-1 text-xs text-zinc-600">
                    MFA code (if your workspace enforces step-up)
                    <input
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      value={otp}
                      onChange={(e) => setOtp(e.target.value)}
                      placeholder="123456"
                      className="w-40 rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none"
                    />
                  </label>

                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => save(k.id)}
                      disabled={busy}
                      className="inline-flex items-center gap-1 rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <FloppyDisk size={14} weight="duotone" />
                      {busy ? "Saving" : "Save windows"}
                    </button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </main>
  );
}
