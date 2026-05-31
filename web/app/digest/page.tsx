"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import {
  Envelope,
  PaperPlaneTilt,
  ChartBar,
  Sparkle,
  Warning,
  CheckCircle,
} from "@phosphor-icons/react/dist/ssr";

import { fetcher } from "@/lib/api";

type CategoryCount = {
  category: string;
  label: string;
  count: number;
  avg_confidence: number;
};

type TopShot = {
  id: string;
  filename: string;
  category: string;
  confidence: number;
  created_at: string;
};

type Summary = {
  period: { days: number; since: string; until: string };
  generated_at: string;
  total_shots: number;
  avg_confidence: number;
  by_category: CategoryCount[];
  top_shots: TopShot[];
  per_day: { date: string; count: number }[];
  empty: boolean;
};

type DigestResponse = { summary: Summary; text: string; html: string };

function pct(n: number): string {
  if (!Number.isFinite(n)) return "0%";
  return `${Math.round(n * 100)}%`;
}

export default function DigestPage() {
  const [days, setDays] = useState<7 | 14 | 30>(7);
  const [to, setTo] = useState("");
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<
    | { ok: true; path: string; subject: string; to: string }
    | { ok: false; message: string }
    | null
  >(null);

  const { data, error, isLoading } = useSWR<DigestResponse>(
    `/api/me/digest?days=${days}`,
    fetcher,
    { revalidateOnFocus: false },
  );

  const summary = data?.summary;
  const maxPerDay = summary
    ? Math.max(1, ...summary.per_day.map((d) => d.count))
    : 1;

  async function onSend() {
    setSending(true);
    setSendResult(null);
    try {
      const res = await fetch("/api/me/digest", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ days, to: to.trim() || undefined }),
      });
      if (!res.ok) {
        const body = await res.text();
        setSendResult({ ok: false, message: body.slice(0, 240) || `HTTP ${res.status}` });
      } else {
        const body = (await res.json()) as {
          path: string;
          subject: string;
          to: string;
        };
        setSendResult({ ok: true, ...body });
      }
    } catch (e) {
      setSendResult({ ok: false, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <header>
        <div className="eyebrow">Activity recap</div>
        <h1 className="h-display text-[34px]">DIGEST</h1>
        <p className="text-[13px] opacity-70 mt-1">
          A weekly snapshot of your classifications. Preview here, send to your
          inbox, or wire up SMTP for scheduled delivery.
        </p>
      </header>

      <div
        className="panel p-4 flex flex-wrap items-center gap-3"
        role="group"
        aria-label="Window"
      >
        <span className="eyebrow">Window</span>
        {[7, 14, 30].map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDays(d as 7 | 14 | 30)}
            aria-pressed={days === d}
            className="px-3 py-1.5 rounded-md text-[12px] border tabular-nums"
            style={{
              background: days === d ? "var(--color-felt)" : "transparent",
              color: days === d ? "var(--color-chalk)" : "inherit",
              borderColor: "var(--color-rule)",
            }}
          >
            {d} days
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <a
            href={`/api/me/digest?days=${days}&format=html`}
            target="_blank"
            rel="noreferrer"
            className="text-[12px] underline opacity-80 hover:opacity-100"
          >
            Open HTML
          </a>
          <a
            href={`/api/me/digest?days=${days}&format=text`}
            target="_blank"
            rel="noreferrer"
            className="text-[12px] underline opacity-80 hover:opacity-100"
          >
            Open text
          </a>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="panel p-4 flex items-start gap-3 text-[13px]"
          style={{ borderColor: "var(--color-warn, #c33)" }}
        >
          <Warning size={18} weight="duotone" />
          <div>
            <div className="font-medium">Could not load digest.</div>
            <div className="opacity-70">{String((error as Error).message ?? error)}</div>
          </div>
        </div>
      )}

      {isLoading && (
        <div className="panel p-6 grid gap-3" aria-busy="true">
          <div className="h-4 w-40 rounded animate-pulse" style={{ background: "var(--color-rule)" }} />
          <div className="h-24 w-full rounded animate-pulse" style={{ background: "var(--color-rule)" }} />
          <div className="h-4 w-72 rounded animate-pulse" style={{ background: "var(--color-rule)" }} />
        </div>
      )}

      {summary && !isLoading && summary.empty && (
        <div className="panel p-8 text-center">
          <div
            className="mx-auto w-12 h-12 rounded-full flex items-center justify-center mb-3"
            style={{ background: "var(--color-chalk)", border: "1px solid var(--color-rule)" }}
          >
            <Sparkle size={22} weight="duotone" />
          </div>
          <h2 className="h-display text-[20px] mb-1">Nothing to recap yet</h2>
          <p className="text-[13px] opacity-70 mb-4">
            Run a classification and your activity will show up here.
          </p>
          <Link
            href="/demo"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px]"
            style={{ background: "var(--color-felt)", color: "var(--color-chalk)" }}
          >
            <PaperPlaneTilt size={16} weight="duotone" /> Try the demo
          </Link>
        </div>
      )}

      {summary && !isLoading && !summary.empty && (
        <>
          <section className="panel p-5 grid gap-4">
            <div className="flex items-center gap-2">
              <ChartBar size={18} weight="duotone" />
              <h2 className="h-display text-[18px]">Last {summary.period.days} days</h2>
              <span className="ml-auto eyebrow">
                {summary.period.since.slice(0, 10)} to {summary.period.until.slice(0, 10)}
              </span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              <div>
                <div className="eyebrow">Total shots</div>
                <div className="font-mono text-[28px] tabular-nums">{summary.total_shots}</div>
              </div>
              <div>
                <div className="eyebrow">Avg confidence</div>
                <div className="font-mono text-[28px] tabular-nums">{pct(summary.avg_confidence)}</div>
              </div>
              <div>
                <div className="eyebrow">Categories</div>
                <div className="font-mono text-[28px] tabular-nums">{summary.by_category.length}</div>
              </div>
            </div>

            <div
              className="flex items-end gap-[3px] h-20 px-1"
              role="img"
              aria-label={`Daily counts, ${summary.per_day.length} days`}
            >
              {summary.per_day.map((d) => {
                const h = Math.max(3, Math.round((d.count / maxPerDay) * 72));
                return (
                  <div
                    key={d.date}
                    className="flex-1"
                    title={`${d.date}: ${d.count}`}
                    style={{
                      height: `${h}px`,
                      background: d.count
                        ? "var(--color-felt)"
                        : "var(--color-rule)",
                      borderRadius: 2,
                    }}
                  />
                );
              })}
            </div>
          </section>

          <section className="grid md:grid-cols-2 gap-4">
            <div className="panel p-5">
              <h3 className="h-display text-[16px] mb-3">By category</h3>
              <ul className="divide-y" style={{ borderColor: "var(--color-rule)" }}>
                {summary.by_category.map((c) => (
                  <li key={c.category} className="flex items-center gap-3 py-2 text-[13px]">
                    <span className="flex-1 truncate">{c.label}</span>
                    <span className="font-mono tabular-nums w-10 text-right">{c.count}</span>
                    <span className="opacity-60 w-12 text-right tabular-nums">{pct(c.avg_confidence)}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="panel p-5">
              <h3 className="h-display text-[16px] mb-3">Top confidence</h3>
              {summary.top_shots.length === 0 ? (
                <p className="text-[13px] opacity-70">No high-confidence shots in this window.</p>
              ) : (
                <ul className="space-y-2">
                  {summary.top_shots.map((t) => (
                    <li key={t.id} className="flex items-center gap-3 text-[13px]">
                      <span className="font-mono tabular-nums w-10">{pct(t.confidence)}</span>
                      <span className="eyebrow w-16 truncate">{t.category}</span>
                      <Link
                        href={`/shots/${t.id}`}
                        className="flex-1 truncate underline-offset-2 hover:underline"
                      >
                        {t.filename}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </>
      )}

      <section className="panel p-5 grid gap-3">
        <div className="flex items-center gap-2">
          <Envelope size={18} weight="duotone" />
          <h2 className="h-display text-[18px]">Send to inbox</h2>
        </div>
        <p className="text-[13px] opacity-70">
          We write a real RFC 5322 message to the digest outbox on the server.
          Set <code className="font-mono">DIGEST_TO</code> and an SMTP relay to
          deliver automatically.
        </p>
        <div className="flex flex-wrap gap-2 items-center">
          <label className="sr-only" htmlFor="digest-to">Recipient</label>
          <input
            id="digest-to"
            type="email"
            inputMode="email"
            placeholder="you@example.com"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="flex-1 min-w-[200px] px-3 py-2 rounded-md text-[13px] border bg-transparent"
            style={{ borderColor: "var(--color-rule)" }}
          />
          <button
            type="button"
            onClick={onSend}
            disabled={sending || isLoading}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px] disabled:opacity-50"
            style={{ background: "var(--color-felt)", color: "var(--color-chalk)" }}
          >
            <PaperPlaneTilt size={16} weight="duotone" />
            {sending ? "Sending..." : `Send last ${days}d`}
          </button>
        </div>
        {sendResult && sendResult.ok && (
          <div
            role="status"
            className="flex items-start gap-2 text-[12px] p-3 rounded-md"
            style={{ background: "var(--color-chalk)", border: "1px solid var(--color-rule)" }}
          >
            <CheckCircle size={16} weight="duotone" />
            <div className="min-w-0">
              <div>Queued to {sendResult.to}.</div>
              <div className="opacity-70 font-mono truncate">{sendResult.path}</div>
            </div>
          </div>
        )}
        {sendResult && !sendResult.ok && (
          <div
            role="alert"
            className="flex items-start gap-2 text-[12px] p-3 rounded-md"
            style={{ background: "var(--color-chalk)", border: "1px solid var(--color-rule)" }}
          >
            <Warning size={16} weight="duotone" />
            <div>Failed: {sendResult.message}</div>
          </div>
        )}
      </section>

      <p className="text-[11px] opacity-60">
        Tip: schedule <code className="font-mono">curl -XPOST $APP/api/me/digest -d &apos;{"{\"days\":7}"}&apos;</code>
        weekly with cron to keep the recap arriving.
      </p>
    </div>
  );
}
