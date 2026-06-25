"use client";

// PinnedQuickBar: a horizontally-scrolling strip of the user's pinned shots
// at the top of the Live page (F15) so they can jump straight back to
// starred work without browsing all shots. Hides entirely when nothing is
// pinned (including the seeded-sample case, since sample rows are never
// pinned) so it never shows hollow chrome. Pulls the same recent-history
// endpoint the rest of the home page already uses.

import Link from "next/link";
import useSWR from "swr";
import { Star, ArrowRight } from "@phosphor-icons/react/dist/ssr";
import { Chip } from "@/components/Chip";
import { ConfBadge } from "@/components/ConfBadge";
import { fetcher, ENDPOINTS } from "@/lib/api";
import { shortId } from "@/lib/categories";
import {
  pinnedQuickItems,
  pinnedOverflow,
  type PinnableShot,
} from "@/lib/pinned-bar";

export default function PinnedQuickBar() {
  const { data } = useSWR<PinnableShot[]>(
    ENDPOINTS.history({ limit: 200, pinned: true }),
    fetcher,
    { refreshInterval: 30_000, revalidateOnFocus: false },
  );

  const items = pinnedQuickItems(data);
  if (items.length === 0) return null;
  const overflow = pinnedOverflow(data);

  return (
    <section aria-label="Pinned shots" data-testid="pinned-quick-bar">
      <div className="flex items-center justify-between mb-2">
        <span className="eyebrow flex items-center gap-1.5">
          <Star size={13} weight="fill" style={{ color: "#b45309" }} />
          Pinned
        </span>
        <Link
          href="/shots?pinned=true"
          className="eyebrow opacity-70 hover:opacity-100 hover:underline flex items-center gap-1"
        >
          View all <ArrowRight size={11} weight="bold" />
        </Link>
      </div>
      <div
        className="flex items-stretch gap-2 overflow-x-auto pb-1"
        style={{ scrollbarWidth: "thin" }}
      >
        {items.map((s) => (
          <Link
            key={s.id}
            href={`/shots/${s.id}`}
            className="panel p-2.5 flex flex-col gap-1.5 shrink-0 w-[180px] transition-shadow hover:shadow-md"
            title={s.name}
          >
            <div className="flex items-center justify-between gap-2">
              <Chip cat={s.primary_category} />
              <Star size={12} weight="fill" style={{ color: "#b45309" }} aria-hidden />
            </div>
            <span className="text-[12px] font-medium truncate">{s.name}</span>
            <div className="flex items-center justify-between gap-2">
              <ConfBadge score={s.confidence} size="sm" variant="ghost" digits={0} />
              <span className="num text-[10px] opacity-50">{shortId(s.id)}</span>
            </div>
          </Link>
        ))}
        {overflow > 0 && (
          <Link
            href="/shots?pinned=true"
            className="panel p-2.5 flex flex-col items-center justify-center gap-1 shrink-0 w-[96px] text-center hover:shadow-md transition-shadow"
          >
            <span className="num text-[18px]">+{overflow}</span>
            <span className="eyebrow opacity-70">more</span>
          </Link>
        )}
      </div>
    </section>
  );
}
