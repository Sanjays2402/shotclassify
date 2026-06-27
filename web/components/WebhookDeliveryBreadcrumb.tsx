"use client";

// WebhookDeliveryBreadcrumb: a slim row of removable pills above the
// /webhooks "Recent deliveries" table showing every active filter
// (Status / Event) with an x to clear each one individually, plus a
// "Clear all" affordance (F92). Mirrors the shots FilterBreadcrumb (F24) and
// the notifications NotifFilterBreadcrumb (F88) so the three list surfaces
// consolidate on one pattern. lib/webhook-delivery-chips owns the
// label-building + which-filters-are-active logic, so this stays a thin
// renderer.

import { X } from "@phosphor-icons/react/dist/ssr";
import {
  activeDeliveryChips,
  type WebhookDeliveryFilterKey,
  type WebhookDeliveryFilterState,
} from "@/lib/webhook-delivery-chips";

export function WebhookDeliveryBreadcrumb({
  filters,
  onClear,
  onClearAll,
}: {
  filters: WebhookDeliveryFilterState;
  // Clear a single filter by key.
  onClear: (key: WebhookDeliveryFilterKey) => void;
  // Clear every filter at once.
  onClearAll: () => void;
}) {
  const chips = activeDeliveryChips(filters);
  if (chips.length === 0) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-2 text-[12px] mb-2"
      role="region"
      aria-label="Active delivery filters"
      data-testid="webhook-delivery-breadcrumb"
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

export default WebhookDeliveryBreadcrumb;
