"use client";

// /api-docs — reference for the public /v1 programmatic API.
// Renders copy-paste curl snippets that use the visitor's current origin so
// the examples are immediately runnable against the local dev server or a
// deployed instance.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  BookOpen,
  Check,
  Copy,
  Key,
  Terminal,
} from "@phosphor-icons/react/dist/ssr";

type Endpoint = {
  id: string;
  method: "GET" | "POST";
  path: string;
  title: string;
  description: string;
  curl: (origin: string) => string;
  response: string;
};

function buildEndpoints(origin: string): Endpoint[] {
  return [
    {
      id: "classify",
      method: "POST",
      path: "/v1/classify",
      title: "Classify an image",
      description:
        "Upload an image as multipart/form-data with field 'file'. Returns the top category, confidence, and the full probability distribution.",
      curl: (o) =>
        `curl -X POST ${o}/v1/classify \\\n  -H "Authorization: Bearer $SHOTCLASSIFY_KEY" \\\n  -F "file=@./shot.jpg"`,
      response: `{
  "id": "sh_01HXYZ...",
  "filename": "shot.jpg",
  "primary_category": "cover_drive",
  "confidence": 0.91,
  "probabilities": { "cover_drive": 0.91, "pull": 0.04, ... }
}`,
    },
    {
      id: "shots-list",
      method: "GET",
      path: "/v1/shots",
      title: "List shots",
      description:
        "Browse saved classifications. Supports limit, offset, category, since, until, min_confidence, q, tag, and sort query parameters. limit is capped at 200.",
      curl: (o) =>
        `curl ${o}/v1/shots?limit=20&category=cover_drive \\\n  -H "Authorization: Bearer $SHOTCLASSIFY_KEY"`,
      response: `[
  {
    "id": "sh_01HXYZ...",
    "filename": "shot.jpg",
    "primary_category": "cover_drive",
    "confidence": 0.91,
    "created_at": "2026-05-30T22:14:00Z"
  }
]`,
    },
    {
      id: "shots-get",
      method: "GET",
      path: "/v1/shots/{id}",
      title: "Get a single shot",
      description:
        "Returns the full classification record including probabilities, OCR text, and any user correction.",
      curl: (o) =>
        `curl ${o}/v1/shots/sh_01HXYZ \\\n  -H "Authorization: Bearer $SHOTCLASSIFY_KEY"`,
      response: `{
  "id": "sh_01HXYZ",
  "filename": "shot.jpg",
  "primary_category": "cover_drive",
  "confidence": 0.91,
  "user_corrected_to": null,
  "created_at": "2026-05-30T22:14:00Z"
}`,
    },
    {
      id: "usage",
      method: "GET",
      path: "/v1/usage",
      title: "Inspect your API key",
      description:
        "Returns metadata for the API key making the request, including total request count and last-used timestamp. Useful for building your own quota meter.",
      curl: (o) =>
        `curl ${o}/v1/usage \\\n  -H "Authorization: Bearer $SHOTCLASSIFY_KEY"`,
      response: `{
  "key": {
    "id": "ak_01HXYZ",
    "name": "production",
    "prefix": "sk_live_abcd",
    "created_at": "2026-05-01T10:00:00Z",
    "last_used_at": "2026-05-30T22:14:00Z",
    "usage_count": 1284
  }
}`,
    },
  ];
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  const onClick = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1400);
    } catch {
      /* clipboard unavailable, no-op */
    }
  }, [text]);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="inline-flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs text-zinc-200 transition hover:border-zinc-500 hover:bg-zinc-800 focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
    >
      {done ? (
        <>
          <Check size={14} weight="duotone" /> Copied
        </>
      ) : (
        <>
          <Copy size={14} weight="duotone" /> Copy
        </>
      )}
    </button>
  );
}

function MethodPill({ method }: { method: "GET" | "POST" }) {
  const color =
    method === "GET"
      ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
      : "bg-sky-500/10 text-sky-300 border-sky-500/30";
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium tracking-wide ${color}`}
    >
      {method}
    </span>
  );
}

export default function ApiDocsPage() {
  const [origin, setOrigin] = useState("http://localhost:3000");

  useEffect(() => {
    if (typeof window !== "undefined") setOrigin(window.location.origin);
  }, []);

  const endpoints = buildEndpoints(origin);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="mb-8">
        <div className="mb-2 flex items-center gap-2 text-emerald-400">
          <BookOpen size={20} weight="duotone" />
          <span className="text-xs font-medium uppercase tracking-wider">
            API reference
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-zinc-100 sm:text-3xl">
          shotclassify v1 API
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-zinc-400">
          A small, predictable REST surface for classifying cricket shots and
          reading back the saved history. Every endpoint authenticates with a
          user-issued API key.
        </p>
      </header>

      <section className="mb-8 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 sm:p-5">
        <div className="mb-3 flex items-center gap-2 text-zinc-200">
          <Key size={16} weight="duotone" className="text-emerald-400" />
          <h2 className="text-sm font-medium">Authentication</h2>
        </div>
        <p className="text-sm leading-relaxed text-zinc-400">
          Pass your key in the <code className="rounded bg-zinc-900 px-1 py-0.5 text-xs text-zinc-200">Authorization</code> header.
          Keys start with <code className="rounded bg-zinc-900 px-1 py-0.5 text-xs text-zinc-200">sk_live_</code> and are shown once
          at creation time.
        </p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <code className="block overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 font-mono text-xs text-zinc-200">
            Authorization: Bearer sk_live_...
          </code>
          <Link
            href="/keys"
            className="inline-flex w-fit items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 transition hover:bg-emerald-500/15"
          >
            <Key size={14} weight="duotone" /> Manage API keys
          </Link>
        </div>
      </section>

      <section className="mb-8 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 sm:p-5">
        <div className="mb-2 flex items-center gap-2 text-zinc-200">
          <Terminal size={16} weight="duotone" className="text-emerald-400" />
          <h2 className="text-sm font-medium">Quick start</h2>
        </div>
        <p className="mb-3 text-sm leading-relaxed text-zinc-400">
          Export your key once, then any snippet below runs as-is.
        </p>
        <div className="relative">
          <pre className="overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900 px-3 py-3 font-mono text-xs leading-relaxed text-zinc-200">
{`export SHOTCLASSIFY_KEY=sk_live_...`}
          </pre>
          <div className="absolute right-2 top-2">
            <CopyButton
              text={`export SHOTCLASSIFY_KEY=sk_live_...`}
              label="Copy export command"
            />
          </div>
        </div>
      </section>

      <section className="space-y-6">
        <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
          Endpoints
        </h2>
        {endpoints.map((ep) => {
          const curl = ep.curl(origin);
          return (
            <article
              key={ep.id}
              id={ep.id}
              className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 sm:p-5"
            >
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <MethodPill method={ep.method} />
                <code className="font-mono text-sm text-zinc-200">
                  {ep.path}
                </code>
              </div>
              <h3 className="mb-1 text-base font-medium text-zinc-100">
                {ep.title}
              </h3>
              <p className="mb-3 text-sm leading-relaxed text-zinc-400">
                {ep.description}
              </p>
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs uppercase tracking-wider text-zinc-500">
                  Request
                </span>
                <CopyButton text={curl} label={`Copy curl for ${ep.title}`} />
              </div>
              <pre className="mb-3 overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900 px-3 py-3 font-mono text-xs leading-relaxed text-zinc-200">
                {curl}
              </pre>
              <div className="mb-2 text-xs uppercase tracking-wider text-zinc-500">
                Response (example)
              </div>
              <pre className="overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900 px-3 py-3 font-mono text-xs leading-relaxed text-zinc-400">
                {ep.response}
              </pre>
            </article>
          );
        })}
      </section>

      <section className="mt-8 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 text-sm text-zinc-400 sm:p-5">
        <h2 className="mb-2 text-sm font-medium text-zinc-200">Errors</h2>
        <p className="leading-relaxed">
          Errors return JSON in the shape{" "}
          <code className="rounded bg-zinc-900 px-1 py-0.5 text-xs text-zinc-200">
            {'{ "error": { "code", "message" } }'}
          </code>
          . Common codes: <code className="text-xs">missing_credentials</code>,{" "}
          <code className="text-xs">invalid_key</code>,{" "}
          <code className="text-xs">invalid_id</code>,{" "}
          <code className="text-xs">not_found</code>,{" "}
          <code className="text-xs">upstream_unreachable</code>.
        </p>
      </section>
    </main>
  );
}
