"use client";

import useSWR from "swr";
import Link from "next/link";
import { fetcher, ENDPOINTS } from "@/lib/api";
import { Chip } from "./Chip";
import { ConfBadge } from "./ConfBadge";
import { ms, type Category } from "@/lib/categories";
import { makeSampleShots } from "@/lib/sample";

type Row = {
  id: string;
  filename: string;
  primary_category: Category;
  confidence: number;
  elapsed_ms?: number;
  source?: string;
  created_at: string;
};

function timeAgo(iso: string): string {
  const t = new Date(iso).getTime();
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

export default function Feed({ limit = 18 }: { limit?: number }) {
  const { data, error, isLoading } = useSWR<any[]>(
    ENDPOINTS.history({ limit }),
    fetcher,
    { refreshInterval: 5_000, revalidateOnFocus: false }
  );

  const isSample = error || !Array.isArray(data) || data.length === 0;
  const rows: Row[] = isSample
    ? (makeSampleShots(limit) as unknown as Row[])
    : (data as Row[]);

  // Duplicate for seamless vertical marquee.
  const stream = [...rows, ...rows];

  return (
    <div className="panel-dark p-0 overflow-hidden h-[520px] relative">
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/10">
        <div className="flex items-center gap-3">
          <span className="live">On air</span>
          <span className="eyebrow" style={{ color: "var(--color-chalk)" }}>
            Classification feed
          </span>
        </div>
        <div className="flex items-center gap-3">
          {isSample && (
            <span
              className="eyebrow"
              style={{ color: "var(--color-cue)" }}
              title="No live records on the server; rendering seeded data."
            >
              ⟂ Sample
            </span>
          )}
          <Link
            href="/shots"
            className="eyebrow underline-offset-2 hover:underline"
            style={{ color: "var(--color-chalk)" }}
          >
            All shots →
          </Link>
        </div>
      </div>

      {isLoading && !rows.length ? (
        <div className="p-6 text-sm opacity-70">Tuning in…</div>
      ) : (
        <div className="feed-mask h-[472px] overflow-hidden feed-pause" aria-live="polite">
          <ul className="feed-rail px-2 py-3">
            {stream.map((r, i) => (
              <li
                key={`${r.id}-${i}`}
                className="grid grid-cols-[18px_minmax(0,1fr)_auto_auto_auto] items-center gap-3 px-3 py-2 rounded-sm hover:bg-white/[0.04]"
              >
                <span
                  className="dot"
                  style={{ ["--bar" as any]: `var(--color-cat-${r.primary_category.split("_")[0]})` }}
                />
                <div className="min-w-0">
                  <div className="truncate text-[13px]">
                    <Link
                      href={`/shots/${r.id}`}
                      className="hover:text-[color:var(--color-cue)]"
                    >
                      {r.filename || r.id}
                    </Link>
                  </div>
                  <div className="num text-[10px] opacity-60">
                    {r.source ?? "api"} · {timeAgo(r.created_at)} ago
                  </div>
                </div>
                <Chip cat={r.primary_category} />
                <span className="w-[78px] flex justify-end">
                  <ConfBadge
                    score={r.confidence}
                    size="sm"
                    variant="ghost"
                    digits={1}
                  />
                </span>
                <span className="num text-[11px] opacity-70 w-[60px] text-right">
                  {ms(r.elapsed_ms ?? 0)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
