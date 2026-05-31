"use client";

import useSWR from "swr";
import Link from "next/link";
import {
  ShieldCheck,
  Buildings,
  MapPin,
  Database,
  ArrowSquareOut,
  Fingerprint,
} from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

type Subprocessor = {
  name: string;
  purpose: string;
  location: string;
  data_categories: string[];
  website: string;
};

type CatalogResponse = {
  version: string;
  processors: Subprocessor[];
  count: number;
};

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-neutral-200 p-5 animate-pulse">
      <div className="h-4 w-1/3 bg-neutral-200 rounded mb-3" />
      <div className="h-3 w-full bg-neutral-100 rounded mb-2" />
      <div className="h-3 w-5/6 bg-neutral-100 rounded mb-2" />
      <div className="h-3 w-2/3 bg-neutral-100 rounded" />
    </div>
  );
}

export default function TrustCenterPage() {
  const { data, error, isLoading } = useSWR<CatalogResponse>(
    "/api/trust/subprocessors",
    fetcher,
    { revalidateOnFocus: false },
  );

  return (
    <main className="mx-auto max-w-4xl px-5 py-10 sm:py-14">
      <header className="mb-8 sm:mb-10">
        <div className="flex items-center gap-3 mb-3">
          <ShieldCheck
            weight="duotone"
            className="h-7 w-7 text-emerald-600"
            aria-hidden
          />
          <span className="text-xs uppercase tracking-wide text-neutral-500 font-medium">
            Trust Center
          </span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-neutral-900">
          Sub-processors
        </h1>
        <p className="mt-3 text-sm sm:text-base text-neutral-600 leading-relaxed max-w-2xl">
          The third-party services we use to operate ShotClassify. Procurement
          and security reviewers can fetch this list at any time without
          credentials, and your workspace owner is notified whenever it
          changes.
        </p>
        {data?.version ? (
          <div className="mt-4 inline-flex items-center gap-2 text-xs text-neutral-500 font-mono">
            <Fingerprint weight="duotone" className="h-4 w-4" aria-hidden />
            <span>catalog version {data.version}</span>
          </div>
        ) : null}
      </header>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : error ? (
        <div
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
        >
          We could not load the sub-processor catalog. Try again in a moment,
          or contact security@shotclassify.example for the latest copy.
        </div>
      ) : !data || data.processors.length === 0 ? (
        <div className="rounded-lg border border-dashed border-neutral-300 p-8 text-center">
          <p className="text-sm text-neutral-600">
            No sub-processors are configured for this deployment.
          </p>
        </div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {data.processors.map((sp) => (
            <li
              key={sp.name}
              className="rounded-lg border border-neutral-200 p-5 hover:border-neutral-300 transition-colors"
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                  <Buildings
                    weight="duotone"
                    className="h-5 w-5 text-indigo-600 shrink-0"
                    aria-hidden
                  />
                  <h2 className="text-base font-semibold text-neutral-900 truncate">
                    {sp.name}
                  </h2>
                </div>
                <a
                  href={sp.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-neutral-400 hover:text-neutral-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
                  aria-label={`${sp.name} trust page`}
                >
                  <ArrowSquareOut weight="duotone" className="h-4 w-4" />
                </a>
              </div>
              <p className="text-sm text-neutral-700 leading-snug mb-3">
                {sp.purpose}
              </p>
              <dl className="space-y-1.5 text-xs text-neutral-600">
                <div className="flex items-start gap-2">
                  <MapPin
                    weight="duotone"
                    className="h-4 w-4 mt-0.5 text-neutral-400 shrink-0"
                    aria-hidden
                  />
                  <dd>{sp.location}</dd>
                </div>
                <div className="flex items-start gap-2">
                  <Database
                    weight="duotone"
                    className="h-4 w-4 mt-0.5 text-neutral-400 shrink-0"
                    aria-hidden
                  />
                  <dd className="flex flex-wrap gap-1">
                    {sp.data_categories.map((cat) => (
                      <span
                        key={cat}
                        className="inline-flex items-center rounded-md bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-700"
                      >
                        {cat}
                      </span>
                    ))}
                  </dd>
                </div>
              </dl>
            </li>
          ))}
        </ul>
      )}

      <footer className="mt-10 pt-6 border-t border-neutral-200 text-xs text-neutral-500">
        Workspace owners can review and acknowledge the catalog at{" "}
        <Link
          href="/settings/trust"
          className="underline underline-offset-2 hover:text-neutral-800"
        >
          settings &rsaquo; trust
        </Link>
        . Programmatic access:{" "}
        <code className="font-mono text-neutral-700">
          GET /v1/trust/subprocessors
        </code>
        .
      </footer>
    </main>
  );
}
