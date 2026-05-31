"use client";

import Link from "next/link";
import useSWR from "swr";
import {
  CheckCircle,
  Lightning,
  Lock,
  Receipt,
  ChartLine,
} from "@phosphor-icons/react/dist/ssr";
import { QuotaMeter } from "@/components/QuotaMeter";
import { fetcher } from "@/lib/api";

type RecentRow = {
  id: string;
  primary_category: string;
  created_at: string;
};

export default function UsagePage() {
  const { data: recent } = useSWR<RecentRow[]>(
    "/api/history?limit=10",
    fetcher,
    { revalidateOnFocus: false },
  );

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <header>
        <div className="eyebrow">Meter room</div>
        <h1 className="h-display text-[34px]">USAGE</h1>
        <p className="text-[13px] opacity-70 mt-1">
          What you have spent this month, what is left, and how to lift the
          ceiling.
        </p>
      </header>

      <QuotaMeter />

      {/* Plans */}
      <section
        id="upgrade"
        className="grid sm:grid-cols-2 gap-4"
        aria-label="Plans"
      >
        <article className="panel p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Receipt size={20} weight="duotone" />
            <h3 className="h-display text-[18px]">Free</h3>
          </div>
          <div className="font-mono text-[28px] tabular-nums">$0</div>
          <ul className="text-[13px] space-y-1.5 opacity-90">
            <li className="flex items-center gap-2">
              <CheckCircle size={14} weight="duotone" /> 200 classifications per
              month
            </li>
            <li className="flex items-center gap-2">
              <CheckCircle size={14} weight="duotone" /> Full history, export,
              and share links
            </li>
            <li className="flex items-center gap-2">
              <CheckCircle size={14} weight="duotone" /> 1 API key
            </li>
          </ul>
          <div className="text-[12px] opacity-60 mt-1">Current plan</div>
        </article>

        <article
          className="panel p-5 flex flex-col gap-3"
          style={{
            borderColor: "var(--color-felt, #0f766e)",
            boxShadow: "0 0 0 1px var(--color-felt, #0f766e) inset",
          }}
        >
          <div className="flex items-center gap-2">
            <Lightning
              size={20}
              weight="duotone"
              style={{ color: "var(--color-cue)" }}
            />
            <h3 className="h-display text-[18px]">Pro</h3>
          </div>
          <div className="font-mono text-[28px] tabular-nums">
            $29<span className="text-[14px] opacity-60">/mo</span>
          </div>
          <ul className="text-[13px] space-y-1.5 opacity-90">
            <li className="flex items-center gap-2">
              <CheckCircle size={14} weight="duotone" /> 10,000 classifications
              per month
            </li>
            <li className="flex items-center gap-2">
              <CheckCircle size={14} weight="duotone" /> Webhooks with retry +
              delivery log
            </li>
            <li className="flex items-center gap-2">
              <CheckCircle size={14} weight="duotone" /> 5 API keys, priority
              queue
            </li>
            <li className="flex items-center gap-2">
              <Lock size={14} weight="duotone" /> Billing coming soon
            </li>
          </ul>
          <button
            type="button"
            className="btn btn-cue mt-1"
            disabled
            aria-disabled="true"
            title="Stripe checkout wiring lands in the next release"
          >
            Upgrade (soon)
          </button>
        </article>
      </section>

      {/* Recent activity */}
      <section className="panel p-5">
        <div className="flex items-center gap-2 mb-3">
          <ChartLine size={20} weight="duotone" />
          <h3 className="h-display text-[18px]">Recent activity</h3>
        </div>
        {!recent ? (
          <div
            className="h-20 w-full animate-pulse rounded-sm"
            style={{ background: "var(--color-rule)" }}
          />
        ) : recent.length === 0 ? (
          <div className="text-[13px] opacity-70">
            No classifications yet. Try the{" "}
            <Link
              href="/demo"
              className="underline hover:opacity-80"
            >
              demo
            </Link>{" "}
            or{" "}
            <Link href="/upload" className="underline hover:opacity-80">
              upload a frame
            </Link>
            .
          </div>
        ) : (
          <ul className="divide-y" style={{ borderColor: "var(--color-rule)" }}>
            {recent.slice(0, 8).map((r) => (
              <li
                key={r.id}
                className="py-2 flex items-center justify-between text-[13px]"
              >
                <Link
                  href={`/shots/${r.id}`}
                  className="font-mono opacity-90 hover:opacity-100"
                >
                  {r.id.slice(0, 8)}
                </Link>
                <span className="eyebrow">{r.primary_category}</span>
                <span className="opacity-60 font-mono tabular-nums">
                  {new Date(r.created_at).toLocaleString(undefined, {
                    month: "short",
                    day: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
