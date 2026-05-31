"use client";

import useSWR from "swr";
import Link from "next/link";
import { Gauge, Lightning, ArrowUpRight } from "@phosphor-icons/react/dist/ssr";
import { fetcher } from "@/lib/api";

export type Usage = {
  principal: string;
  tenant_id: string | null;
  plan: string;
  period: string;
  period_start: string;
  period_end: string;
  limit: number;
  used: number;
  remaining: number;
  percent: number;
  over_limit: boolean;
};

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function barColor(pct: number, over: boolean): string {
  if (over) return "var(--color-cue, #ef4444)";
  if (pct >= 0.9) return "var(--color-cue, #f59e0b)";
  if (pct >= 0.7) return "#f59e0b";
  return "var(--color-felt, #0f766e)";
}

export function QuotaMeter({ compact = false }: { compact?: boolean }) {
  const { data, error, isLoading } = useSWR<Usage>("/api/me/usage", fetcher, {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });

  if (isLoading) {
    return (
      <div
        className={compact ? "h-6 w-44 animate-pulse rounded-sm" : "h-24 w-full animate-pulse rounded-md"}
        style={{ background: "var(--color-rule)" }}
        aria-label="Loading usage"
      />
    );
  }

  const unauth = error && (error as Error & { status?: number }).status === 401;
  if (unauth || !data) {
    if (compact) return null;
    return (
      <div className="panel p-4 text-[13px] opacity-70">
        Sign in to see your monthly usage.
      </div>
    );
  }

  const pct = Math.min(1, Math.max(0, data.percent));
  const widthPct = `${Math.round(pct * 100)}%`;
  const color = barColor(pct, data.over_limit);

  if (compact) {
    return (
      <Link
        href="/usage"
        className="flex items-center gap-2 text-[12px] hover:opacity-80 transition-opacity"
        title={`${data.used} of ${data.limit} this month`}
      >
        <Gauge size={16} weight="duotone" style={{ color }} />
        <span className="font-mono tabular-nums">
          {data.used}/{data.limit}
        </span>
        <span
          className="h-1.5 w-16 rounded-full overflow-hidden"
          style={{ background: "var(--color-rule)" }}
          aria-hidden
        >
          <span
            className="block h-full rounded-full transition-[width] duration-500"
            style={{ width: widthPct, background: color }}
          />
        </span>
      </Link>
    );
  }

  return (
    <section className="panel p-5 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <Gauge size={28} weight="duotone" className="opacity-80" />
          <div>
            <div className="eyebrow">Plan {data.plan}</div>
            <h2 className="h-display text-[22px] leading-tight">
              {data.used.toLocaleString()} of {data.limit.toLocaleString()} classifications
            </h2>
            <div className="text-[12px] opacity-70 mt-1">
              Resets {fmtDate(data.period_end)} (UTC). Period started{" "}
              {fmtDate(data.period_start)}.
            </div>
          </div>
        </div>
        {data.over_limit ? (
          <Link
            href="#upgrade"
            className="btn btn-cue inline-flex items-center gap-1.5"
          >
            <Lightning size={16} weight="duotone" />
            Upgrade
            <ArrowUpRight size={14} weight="bold" />
          </Link>
        ) : (
          <div className="text-right">
            <div className="font-mono tabular-nums text-[20px]">
              {data.remaining.toLocaleString()}
            </div>
            <div className="eyebrow">left this month</div>
          </div>
        )}
      </div>

      <div>
        <div
          className="h-2.5 w-full rounded-full overflow-hidden"
          style={{ background: "var(--color-rule)" }}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={data.limit}
          aria-valuenow={data.used}
          aria-label="Monthly usage"
        >
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{ width: widthPct, background: color }}
          />
        </div>
        <div className="flex justify-between text-[11px] opacity-70 mt-1.5 font-mono tabular-nums">
          <span>0</span>
          <span>{Math.round(pct * 100)}% used</span>
          <span>{data.limit.toLocaleString()}</span>
        </div>
      </div>

      {data.over_limit && (
        <div
          className="text-[13px] p-3 rounded-md"
          style={{
            background: "rgba(239, 68, 68, 0.08)",
            border: "1px solid rgba(239, 68, 68, 0.25)",
          }}
          role="alert"
        >
          You hit the free-tier ceiling. New classify requests will return 402
          until the period resets or you upgrade.
        </div>
      )}
    </section>
  );
}

export default QuotaMeter;
