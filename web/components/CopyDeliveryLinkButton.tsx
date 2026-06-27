"use client";

// "Copy link" button for the /webhooks deliveries view (F113). Now that the
// status + event filter persists to the URL (F103), a teammate can be handed a
// link that reopens the exact triage view. This serialises the page's CURRENT
// delivery filter into an absolute URL and copies it, mirroring the /shots
// CopyViewLinkButton: same secure-context-aware clipboard write + app toast.
// Disabled when no filter is active -- a link to the unfiltered deliveries list
// is just the page itself, so there's nothing to share.

import { useCallback } from "react";
import { LinkSimple } from "@phosphor-icons/react/dist/ssr";
import {
  buildDeliveryDeepLink,
  deliveryLinkToastMessage,
  hasDeliveryFilter,
} from "@/lib/webhook-delivery-url";
import type { WebhookDeliveryFilterState } from "@/lib/webhook-delivery-chips";
import { toast } from "@/lib/toast-store";

async function writeClipboard(text: string): Promise<void> {
  if (
    typeof navigator !== "undefined" &&
    navigator.clipboard &&
    typeof window !== "undefined" &&
    window.isSecureContext
  ) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // Fallback for non-secure contexts (older Safari, http dev).
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

export default function CopyDeliveryLinkButton({
  filters,
  disabled,
}: {
  filters: WebhookDeliveryFilterState;
  disabled?: boolean;
}) {
  // Disable when nothing constrains the list -- a link to the bare deliveries
  // view is the same as the page itself. Recomputed from the same predicate
  // the URL writer uses so the button and the link agree.
  const active = hasDeliveryFilter(filters);

  const copy = useCallback(async () => {
    const base =
      typeof window !== "undefined"
        ? `${window.location.origin}/webhooks`
        : "/webhooks";
    const url = buildDeliveryDeepLink(filters, base);
    try {
      await writeClipboard(url);
      toast.success(deliveryLinkToastMessage(filters));
    } catch {
      toast.error("Copy failed. Your browser blocked clipboard access.");
    }
  }, [filters]);

  const off = disabled || !active;

  return (
    <button
      type="button"
      onClick={copy}
      disabled={off}
      aria-label="Copy a shareable link to this filtered deliveries view"
      title={
        active
          ? "Copy a link that reopens this exact filtered deliveries view"
          : "Apply a filter to share a link to it"
      }
      className="btn btn-ghost text-[12px] inline-flex items-center gap-1.5"
    >
      <LinkSimple size={14} weight="duotone" /> Copy link
    </button>
  );
}
