"use client";

// NotifFilterBreadcrumb: a slim row of removable pills above the notifications
// list showing every active filter (Search / Kind / Unread only) with an x to
// clear each one individually, plus a "Clear all" affordance (F88). Mirrors
// the shots-table FilterBreadcrumb so the two surfaces consolidate on one
// pattern. lib/notif-filter-chips owns the label-building + which-filters-are-
// active logic, so this component stays a thin renderer.

import { X } from "@phosphor-icons/react/dist/ssr";
import {
  activeNotifChips,
  type NotifFilterKey,
  type NotifFilterState,
} from "@/lib/notif-filter-chips";

export function NotifFilterBreadcrumb({
  filters,
  onClear,
  onClearAll,
}: {
  filters: NotifFilterState;
  // Clear a single filter by key.
  onClear: (key: NotifFilterKey) => void;
  // Clear every filter at once.
  onClearAll: () => void;
}) {
  const chips = activeNotifChips(filters);
  if (chips.length === 0) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-2 text-[12px] mb-2"
      role="region"
      aria-label="Active filters"
      data-testid="notif-filter-breadcrumb"
    >
      <span className="eyebrow">Filtering</span>
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex items-center gap-1.5 rounded-sm border pl-2 pr-1 py-[2px]"
          style={{
            borderColor: "var(--color-rule)",
            background: "var(--color-chalk-2)",
          }}
        >
          <span className="eyebrow opacity-60">{chip.field}</span>
          {chip.value && <span className="num">{chip.value}</span>}
          <button
            type="button"
            onClick={() => onClear(chip.key)}
            aria-label={`Clear filter ${chip.label}`}
            title={`Clear ${chip.label}`}
            className="inline-flex items-center justify-center w-4 h-4 rounded-sm hover:bg-black/[0.08] transition-colors"
            style={{ color: "var(--color-ink)" }}
          >
            <X size={11} weight="bold" />
          </button>
        </span>
      ))}
      {chips.length > 1 && (
        <button
          type="button"
          onClick={onClearAll}
          className="eyebrow hover:underline opacity-70 hover:opacity-100"
          title="Clear every filter"
        >
          Clear all
        </button>
      )}
    </div>
  );
}

export default NotifFilterBreadcrumb;
