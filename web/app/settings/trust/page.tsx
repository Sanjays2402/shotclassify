"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  ShieldCheck,
  Warning,
  CheckCircle,
  Clock,
  Fingerprint,
  Buildings,
  ArrowSquareOut,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Subprocessor = {
  name: string;
  purpose: string;
  location: string;
  data_categories: string[];
  website: string;
};

type Ack = {
  tenant_id: string;
  version: string;
  acknowledged_by: string;
  acknowledged_at: string;
  acknowledged_ip: string | null;
  user_agent: string | null;
};

type AckStatus = {
  tenant_id: string;
  catalog: { version: string; processors: Subprocessor[]; count: number };
  acknowledgement: Ack | null;
  acknowledged: boolean;
  stale: boolean;
};

type ApiError = Error & { status?: number };

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  const s = Math.round(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

export default function TrustSettingsPage() {
  const { data, error, isLoading, mutate } = useSWR<AckStatus>(
    "/api/trust/subprocessors/ack",
    fetcher,
    { revalidateOnFocus: false },
  );

  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<
    { kind: "ok" | "err"; msg: string } | null
  >(null);

  const banner = useMemo(() => {
    if (!data) return null;
    if (!data.acknowledgement) {
      return {
        kind: "warn" as const,
        title: "Action required",
        msg: "Review and acknowledge the current sub-processor catalog so your workspace stays compliant with vendor change-notice terms.",
      };
    }
    if (data.stale) {
      return {
        kind: "warn" as const,
        title: "Catalog updated",
        msg: "The sub-processor list changed since your last acknowledgement. Review the differences below and re-acknowledge.",
      };
    }
    return {
      kind: "ok" as const,
      title: "Acknowledged",
      msg: `Current catalog accepted by ${data.acknowledgement.acknowledged_by} ${relativeTime(data.acknowledgement.acknowledged_at)}.`,
    };
  }, [data]);

  async function onAcknowledge() {
    if (!data) return;
    setBusy(true);
    setFlash(null);
    try {
      const r = await fetch("/api/trust/subprocessors/ack", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ version: data.catalog.version }),
      });
      if (!r.ok) {
        const text = await r.text();
        let detail = text;
        try {
          detail = JSON.parse(text).detail ?? text;
        } catch {}
        throw Object.assign(new Error(detail || r.statusText), {
          status: r.status,
        }) as ApiError;
      }
      await mutate();
      setFlash({ kind: "ok", msg: "Catalog acknowledged." });
    } catch (e) {
      const err = e as ApiError;
      setFlash({
        kind: "err",
        msg:
          err.status === 403
            ? "Only workspace admins can acknowledge the sub-processor catalog."
            : err.status === 409
              ? "The catalog changed while this page was open. Reload and review again."
              : err.message || "Could not record acknowledgement.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-5 py-8 sm:py-12">
      <header className="mb-6 sm:mb-8">
        <Link
          href="/settings/security"
          className="text-xs text-neutral-500 hover:text-neutral-800"
        >
          &larr; Security
        </Link>
        <div className="flex items-center gap-3 mt-3 mb-2">
          <ShieldCheck
            weight="duotone"
            className="h-6 w-6 text-emerald-600"
            aria-hidden
          />
          <h1 className="text-xl sm:text-2xl font-semibold tracking-tight text-neutral-900">
            Sub-processor acknowledgement
          </h1>
        </div>
        <p className="text-sm text-neutral-600 leading-relaxed max-w-2xl">
          Review the third-party services that process your workspace data.
          The catalog is also published at{" "}
          <Link
            href="/trust"
            className="underline underline-offset-2 hover:text-neutral-800"
          >
            /trust
          </Link>{" "}
          for procurement reviewers.
        </p>
      </header>

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
        >
          {(error as ApiError).status === 403
            ? "Admin role required to view acknowledgement state."
            : "Could not load acknowledgement state."}
        </div>
      ) : isLoading || !data ? (
        <div className="space-y-3">
          <div className="h-14 rounded-lg bg-neutral-100 animate-pulse" />
          <div className="h-24 rounded-lg bg-neutral-100 animate-pulse" />
          <div className="h-24 rounded-lg bg-neutral-100 animate-pulse" />
        </div>
      ) : (
        <>
          {banner ? (
            <div
              role="status"
              className={
                "rounded-lg border px-4 py-3 mb-5 flex items-start gap-3 " +
                (banner.kind === "ok"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                  : "border-amber-200 bg-amber-50 text-amber-900")
              }
            >
              {banner.kind === "ok" ? (
                <CheckCircle
                  weight="duotone"
                  className="h-5 w-5 mt-0.5 text-emerald-600 shrink-0"
                  aria-hidden
                />
              ) : (
                <Warning
                  weight="duotone"
                  className="h-5 w-5 mt-0.5 text-amber-600 shrink-0"
                  aria-hidden
                />
              )}
              <div className="text-sm">
                <div className="font-medium">{banner.title}</div>
                <div className="mt-0.5">{banner.msg}</div>
              </div>
            </div>
          ) : null}

          <section className="mb-6 rounded-lg border border-neutral-200 p-4 sm:p-5">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div>
                <div className="text-sm font-medium text-neutral-900">
                  Current catalog
                </div>
                <div className="mt-1 inline-flex items-center gap-1.5 text-xs text-neutral-500 font-mono">
                  <Fingerprint
                    weight="duotone"
                    className="h-3.5 w-3.5"
                    aria-hidden
                  />
                  {data.catalog.version} &middot; {data.catalog.count}{" "}
                  processors
                </div>
              </div>
              <button
                type="button"
                onClick={onAcknowledge}
                disabled={busy || data.acknowledged}
                className="inline-flex items-center gap-1.5 rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-800 disabled:bg-neutral-300 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-700 focus-visible:ring-offset-2"
              >
                {busy
                  ? "Recording..."
                  : data.acknowledged
                    ? "Acknowledged"
                    : "Acknowledge catalog"}
              </button>
            </div>
            {data.acknowledgement ? (
              <dl className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-xs text-neutral-600">
                <div className="flex items-center gap-2">
                  <Clock
                    weight="duotone"
                    className="h-4 w-4 text-neutral-400"
                    aria-hidden
                  />
                  <dt className="sr-only">Acknowledged at</dt>
                  <dd>
                    {new Date(
                      data.acknowledgement.acknowledged_at,
                    ).toLocaleString()}
                  </dd>
                </div>
                <div className="flex items-center gap-2">
                  <dt className="font-medium text-neutral-700">By</dt>
                  <dd className="font-mono truncate">
                    {data.acknowledgement.acknowledged_by}
                  </dd>
                </div>
                {data.acknowledgement.acknowledged_ip ? (
                  <div className="flex items-center gap-2">
                    <dt className="font-medium text-neutral-700">From IP</dt>
                    <dd className="font-mono">
                      {data.acknowledgement.acknowledged_ip}
                    </dd>
                  </div>
                ) : null}
                <div className="flex items-center gap-2">
                  <dt className="font-medium text-neutral-700">Version</dt>
                  <dd className="font-mono">
                    {data.acknowledgement.version}
                  </dd>
                </div>
              </dl>
            ) : null}
            {flash ? (
              <div
                role="status"
                className={
                  "mt-3 text-xs " +
                  (flash.kind === "ok" ? "text-emerald-700" : "text-rose-700")
                }
              >
                {flash.msg}
              </div>
            ) : null}
          </section>

          <h2 className="text-sm font-medium text-neutral-900 mb-3">
            Processors ({data.catalog.count})
          </h2>
          <ul className="space-y-3">
            {data.catalog.processors.map((sp) => (
              <li
                key={sp.name}
                className="rounded-lg border border-neutral-200 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <Buildings
                      weight="duotone"
                      className="h-5 w-5 text-indigo-600 shrink-0"
                      aria-hidden
                    />
                    <h3 className="text-sm font-semibold text-neutral-900 truncate">
                      {sp.name}
                    </h3>
                  </div>
                  <a
                    href={sp.website}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-neutral-400 hover:text-neutral-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
                    aria-label={`${sp.name} trust page`}
                  >
                    <ArrowSquareOut
                      weight="duotone"
                      className="h-4 w-4"
                    />
                  </a>
                </div>
                <p className="mt-1.5 text-sm text-neutral-700">{sp.purpose}</p>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-500">
                  <span>{sp.location}</span>
                  <span className="text-neutral-300">&middot;</span>
                  <span>{sp.data_categories.join(", ")}</span>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
