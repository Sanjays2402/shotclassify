"use client";

// Workspace-admin view onto the Next.js server's observability surface.
// Renders the raw Prometheus exposition and the live result of the /healthz
// and /readyz probes so an owner can verify the deployment is being scraped
// correctly without needing kubectl access. No mutations; pure GET.

import { useEffect, useState } from "react";
import {
  Pulse,
  Heartbeat,
  CheckCircle,
  WarningCircle,
  ArrowClockwise,
  Copy,
} from "@phosphor-icons/react/dist/ssr";

type Health = { status: string; uptime_seconds?: number };
type ReadyCheck = { name: string; ok: boolean; detail?: string };
type Ready = { status: string; checks: ReadyCheck[] };

async function fetchText(url: string): Promise<{ status: number; body: string }> {
  const r = await fetch(url, { cache: "no-store" });
  return { status: r.status, body: await r.text() };
}

function MetricsSkeleton() {
  return (
    <div className="space-y-2" aria-busy="true">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="h-3 rounded bg-neutral-200 dark:bg-neutral-800 animate-pulse"
          style={{ width: `${40 + ((i * 7) % 55)}%` }}
        />
      ))}
    </div>
  );
}

export default function ObservabilityPage() {
  const [metrics, setMetrics] = useState<string | null>(null);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [health, setHealth] = useState<{ ok: boolean; data: Health | null }>({
    ok: false,
    data: null,
  });
  const [ready, setReady] = useState<{ ok: boolean; data: Ready | null }>({
    ok: false,
    data: null,
  });
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  async function load() {
    setLoading(true);
    setMetricsError(null);
    try {
      const [m, h, r] = await Promise.all([
        fetchText("/metrics"),
        fetchText("/healthz"),
        fetchText("/readyz"),
      ]);
      setMetrics(m.status === 200 ? m.body : null);
      if (m.status !== 200) setMetricsError(`status ${m.status}`);
      try {
        setHealth({ ok: h.status === 200, data: JSON.parse(h.body) });
      } catch {
        setHealth({ ok: false, data: null });
      }
      try {
        setReady({ ok: r.status === 200, data: JSON.parse(r.body) });
      } catch {
        setReady({ ok: false, data: null });
      }
    } catch (e) {
      setMetricsError(e instanceof Error ? e.message : "fetch failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  async function copyMetrics() {
    if (!metrics) return;
    try {
      await navigator.clipboard.writeText(metrics);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 sm:px-6 py-8 sm:py-10 space-y-8">
      <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Pulse size={26} weight="duotone" className="text-blue-600" />
            Observability
          </h1>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
            Live view of the same probes Prometheus and your load balancer scrape.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 px-3 py-1.5 text-sm hover:border-neutral-400 dark:hover:border-neutral-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
          aria-label="Refresh probes"
        >
          <ArrowClockwise size={16} weight="duotone" />
          Refresh
        </button>
      </header>

      <section className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <ProbeCard
          title="Liveness /healthz"
          icon={<Heartbeat size={20} weight="duotone" className="text-rose-500" />}
          ok={health.ok}
          loading={loading && !health.data}
        >
          {health.data ? (
            <dl className="text-sm space-y-1">
              <Row k="status" v={health.data.status} />
              {typeof health.data.uptime_seconds === "number" && (
                <Row k="uptime_seconds" v={String(health.data.uptime_seconds)} />
              )}
            </dl>
          ) : (
            <Empty text="No response" />
          )}
        </ProbeCard>

        <ProbeCard
          title="Readiness /readyz"
          icon={<Pulse size={20} weight="duotone" className="text-emerald-500" />}
          ok={ready.ok}
          loading={loading && !ready.data}
        >
          {ready.data ? (
            <ul className="text-sm space-y-1.5">
              {ready.data.checks.map((c) => (
                <li key={c.name} className="flex items-start gap-2">
                  {c.ok ? (
                    <CheckCircle
                      size={16}
                      weight="duotone"
                      className="text-emerald-500 mt-0.5 shrink-0"
                    />
                  ) : (
                    <WarningCircle
                      size={16}
                      weight="duotone"
                      className="text-amber-500 mt-0.5 shrink-0"
                    />
                  )}
                  <div className="min-w-0">
                    <div className="font-mono text-xs sm:text-sm">{c.name}</div>
                    {c.detail && (
                      <div className="text-xs text-neutral-500 break-words">
                        {c.detail}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty text="No response" />
          )}
        </ProbeCard>
      </section>

      <section className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-neutral-200 dark:border-neutral-800">
          <div>
            <h2 className="text-sm font-medium">/metrics (Prometheus)</h2>
            <p className="text-xs text-neutral-500">
              Scraped every 15s by Prometheus. Live render below.
            </p>
          </div>
          <button
            type="button"
            onClick={copyMetrics}
            disabled={!metrics}
            className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 dark:border-neutral-800 px-2.5 py-1 text-xs hover:border-neutral-400 dark:hover:border-neutral-600 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Copy metrics"
          >
            <Copy size={14} weight="duotone" />
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <div className="p-4">
          {loading && !metrics ? (
            <MetricsSkeleton />
          ) : metricsError ? (
            <p className="text-sm text-rose-600">Failed to load metrics: {metricsError}</p>
          ) : metrics ? (
            <pre className="text-[11px] sm:text-xs font-mono leading-relaxed text-neutral-700 dark:text-neutral-300 overflow-x-auto whitespace-pre-wrap break-words max-h-[60vh]">
              {metrics}
            </pre>
          ) : (
            <Empty text="No metrics recorded yet. Call any /v1 endpoint." />
          )}
        </div>
      </section>
    </main>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-neutral-500">{k}</dt>
      <dd className="font-mono">{v}</dd>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-neutral-500">{text}</p>;
}

function ProbeCard({
  title,
  icon,
  ok,
  loading,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  ok: boolean;
  loading: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="text-sm font-medium">{title}</h2>
        </div>
        {loading ? (
          <span className="text-xs text-neutral-500">checking</span>
        ) : ok ? (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-600">
            <CheckCircle size={14} weight="duotone" /> healthy
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-amber-600">
            <WarningCircle size={14} weight="duotone" /> degraded
          </span>
        )}
      </div>
      {loading ? <MetricsSkeleton /> : children}
    </div>
  );
}
