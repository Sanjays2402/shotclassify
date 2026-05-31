"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  ShieldCheck,
  Eraser,
  Globe,
  FloppyDisk,
  Warning,
  CheckCircle,
  Lock,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type PrivacyResponse = {
  tenant_id: string;
  redact_modes: string[];
  data_residency: string | null;
  available_modes: string[];
};

type ApiError = Error & { status?: number };

const MODE_COPY: Record<string, { title: string; sub: string }> = {
  email: { title: "Email addresses", sub: "Replace alice@acme.com with [REDACTED:email]" },
  phone: { title: "Phone numbers", sub: "Strip NANP-style numbers from OCR text" },
  ssn: { title: "US Social Security numbers", sub: "Match 3-2-4 with invalid-area filter" },
  credit_card: { title: "Credit card numbers", sub: "13 to 19 digit runs that pass Luhn" },
  ip: { title: "IPv4 addresses", sub: "Dotted quads in logs and stack traces" },
  iban: { title: "IBAN bank accounts", sub: "International account numbers" },
};

const RESIDENCY_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Not configured" },
  { value: "us", label: "United States (us)" },
  { value: "eu", label: "European Union (eu)" },
  { value: "uk", label: "United Kingdom (uk)" },
  { value: "ca", label: "Canada (ca)" },
  { value: "au", label: "Australia (au)" },
  { value: "ap", label: "Asia Pacific (ap)" },
];

export default function PrivacySettingsPage() {
  const { data, error, isLoading, mutate } = useSWR<PrivacyResponse>(
    "/api/settings/security/privacy",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [modes, setModes] = useState<string[]>([]);
  const [residency, setResidency] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; msg: string } | null>(
    null,
  );

  useEffect(() => {
    if (data) {
      setModes(data.redact_modes ?? []);
      setResidency(data.data_residency ?? "");
    }
  }, [data]);

  const status = error as ApiError | undefined;
  const unauth = status?.status === 401;
  const forbidden = status?.status === 403;

  const available = data?.available_modes ?? Object.keys(MODE_COPY);

  const dirty = useMemo(() => {
    if (!data) return false;
    const a = [...(data.redact_modes ?? [])].sort();
    const b = [...modes].sort();
    if (a.length !== b.length) return true;
    if (a.some((v, i) => v !== b[i])) return true;
    return (data.data_residency ?? "") !== residency;
  }, [data, modes, residency]);

  const toggleMode = (mode: string) => {
    setModes((cur) =>
      cur.includes(mode) ? cur.filter((m) => m !== mode) : [...cur, mode],
    );
  };

  const save = async () => {
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/settings/security/privacy", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          redact_modes: modes,
          data_residency: residency || null,
        }),
      });
      if (r.status === 401) {
        setFlash({ kind: "err", msg: "Sign in again to save privacy settings." });
      } else if (r.status === 403) {
        setFlash({ kind: "err", msg: "Admin role required." });
      } else if (!r.ok) {
        const t = await r.text();
        setFlash({ kind: "err", msg: `Save failed: ${t.slice(0, 240)}` });
      } else {
        setFlash({ kind: "ok", msg: "Privacy settings saved." });
        await mutate();
      }
    } catch (e) {
      setFlash({ kind: "err", msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="mb-6 flex items-start gap-3">
        <ShieldCheck size={32} weight="duotone" className="mt-1 text-indigo-500" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Privacy and residency</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Redact PII in OCR text and extracted fields before it is stored
            or shipped to webhooks. Set a data residency label that this
            workspace echoes back to every API response.
          </p>
        </div>
      </header>

      {isLoading && (
        <div className="space-y-3" aria-busy="true">
          <div className="h-20 animate-pulse rounded-lg border border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900" />
          <div className="h-40 animate-pulse rounded-lg border border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900" />
        </div>
      )}

      {unauth && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
          <Lock size={20} weight="duotone" />
          <span>Sign in as an admin to view privacy settings.</span>
        </div>
      )}

      {forbidden && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-900 dark:border-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
          <Warning size={20} weight="duotone" />
          <span>Admin role required to change privacy settings.</span>
        </div>
      )}

      {data && (
        <div className="space-y-6">
          <section className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-950">
            <div className="mb-3 flex items-center gap-2">
              <Eraser size={20} weight="duotone" className="text-indigo-500" />
              <h2 className="text-base font-medium">PII redaction</h2>
            </div>
            <p className="mb-4 text-sm text-neutral-500">
              Selected categories are replaced with a typed placeholder
              such as <code className="rounded bg-neutral-100 px-1 py-0.5 text-xs dark:bg-neutral-900">[REDACTED:email]</code>{" "}
              before the classification is persisted or sent to a webhook.
              Classification accuracy is unaffected because the model sees
              the original image and OCR.
            </p>
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {available.map((m) => {
                const copy = MODE_COPY[m] ?? { title: m, sub: "" };
                const on = modes.includes(m);
                return (
                  <li key={m}>
                    <label
                      className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                        on
                          ? "border-indigo-400 bg-indigo-50/60 dark:border-indigo-600 dark:bg-indigo-950/30"
                          : "border-neutral-200 hover:border-neutral-300 dark:border-neutral-800 dark:hover:border-neutral-700"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 rounded border-neutral-300 text-indigo-600 focus:ring-indigo-500"
                        checked={on}
                        onChange={() => toggleMode(m)}
                        aria-label={`Redact ${copy.title}`}
                      />
                      <div className="min-w-0">
                        <div className="text-sm font-medium">{copy.title}</div>
                        {copy.sub && (
                          <div className="text-xs text-neutral-500">{copy.sub}</div>
                        )}
                      </div>
                    </label>
                  </li>
                );
              })}
            </ul>
          </section>

          <section className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-950">
            <div className="mb-3 flex items-center gap-2">
              <Globe size={20} weight="duotone" className="text-indigo-500" />
              <h2 className="text-base font-medium">Data residency</h2>
            </div>
            <p className="mb-4 text-sm text-neutral-500">
              This label is echoed to every API response in the{" "}
              <code className="rounded bg-neutral-100 px-1 py-0.5 text-xs dark:bg-neutral-900">X-Data-Residency</code>{" "}
              header so a reviewer can verify the region in a single curl.
              Storage backend selection is configured at deploy time.
            </p>
            <label className="block text-sm font-medium" htmlFor="residency">
              Region label
            </label>
            <select
              id="residency"
              className="mt-2 block w-full max-w-sm rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-neutral-700 dark:bg-neutral-950"
              value={residency}
              onChange={(e) => setResidency(e.target.value)}
            >
              {RESIDENCY_OPTIONS.map((o) => (
                <option key={o.value || "none"} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </section>

          <div className="flex items-center justify-between gap-3">
            <div className="min-h-[1.25rem] text-sm" role="status">
              {flash?.kind === "ok" && (
                <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400">
                  <CheckCircle size={16} weight="duotone" />
                  {flash.msg}
                </span>
              )}
              {flash?.kind === "err" && (
                <span className="inline-flex items-center gap-1 text-rose-700 dark:text-rose-400">
                  <Warning size={16} weight="duotone" />
                  {flash.msg}
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={save}
              disabled={!dirty || busy}
              className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-neutral-300 dark:disabled:bg-neutral-800"
            >
              <FloppyDisk size={16} weight="duotone" />
              {busy ? "Saving" : "Save changes"}
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
