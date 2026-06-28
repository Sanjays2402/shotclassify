"use client";

// Per-row "Copy as ..." export menu for the /webhooks "Recent deliveries"
// table (F123). Mirrors the /shots RowExportMenu (F97) so the two list
// surfaces feel identical: a compact dots button opens a small dropdown, and
// copying reports via the app toast. It reuses the shared DELIVERY_EXPORT_FORMATS
// catalogue + the delivery serializers (deliveryToJson / deliveryToMarkdown),
// the roving-index keyboard math (F114), and the same non-secure-context
// clipboard fallback. Presentation-only beyond the clipboard write -- the row
// already holds everything the serializers need, no new endpoint.

import { useEffect, useRef, useState } from "react";
import {
  DotsThreeOutline,
  BracketsCurly,
  MarkdownLogo,
} from "@phosphor-icons/react/dist/ssr";
import {
  serializeDelivery,
  DELIVERY_EXPORT_FORMATS,
  type DeliveryExportFormatKey,
  type DeliveryExportInput,
} from "@/lib/delivery-export";
import { rovingIndex, isRovingKey } from "@/lib/roving-index";
import { toast } from "@/lib/toast-store";

// Clipboard write with a non-secure-context fallback, mirroring RowExportMenu
// so http dev / older Safari still copy.
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
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

const ICONS: Record<DeliveryExportFormatKey, React.ReactNode> = {
  json: <BracketsCurly size={14} weight="duotone" />,
  markdown: <MarkdownLogo size={14} weight="duotone" />,
};

export default function DeliveryExportMenu({
  delivery,
  shortId,
}: {
  // The delivery row this menu copies.
  delivery: DeliveryExportInput;
  // A short id for the toast / aria so a copy from a dense table is traceable.
  shortId: string;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  // Roving focus (F114): -1 = nothing focused yet, so the first ArrowDown
  // lands on the top item.
  const [activeIndex, setActiveIndex] = useState(-1);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  // Prime the roving focus on open, reset on close.
  useEffect(() => {
    if (open) setActiveIndex(0);
    else setActiveIndex(-1);
  }, [open]);

  useEffect(() => {
    if (!open || activeIndex < 0) return;
    itemRefs.current[activeIndex]?.focus();
  }, [open, activeIndex]);

  function onMenuKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (!isRovingKey(e.key)) return;
    const next = rovingIndex(activeIndex, DELIVERY_EXPORT_FORMATS.length, e.key);
    if (next == null) return;
    e.preventDefault();
    setActiveIndex(next);
  }

  async function copy(format: DeliveryExportFormatKey, noun: string) {
    try {
      await writeClipboard(serializeDelivery(format, delivery));
      toast.success(`Copied ${shortId} as ${noun}.`);
    } catch {
      toast.error("Copy failed. Your browser blocked clipboard access.");
    } finally {
      setOpen(false);
    }
  }

  return (
    <div ref={wrapRef} className="relative inline-flex">
      <button
        type="button"
        className="inline-flex items-center justify-center w-6 h-6 rounded-sm hover:bg-black/[0.06]"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Copy delivery ${shortId} as JSON or Markdown`}
        title="Copy as JSON / Markdown"
        onClick={(e) => {
          e.preventDefault();
          setOpen((v) => !v);
        }}
      >
        <DotsThreeOutline size={14} weight="duotone" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1 z-20 min-w-[150px] panel p-1 shadow-lg bg-white"
          style={{ borderColor: "var(--color-rule)" }}
          onKeyDown={onMenuKeyDown}
        >
          {DELIVERY_EXPORT_FORMATS.map((f, i) => (
            <button
              key={f.key}
              ref={(el) => {
                itemRefs.current[i] = el;
              }}
              role="menuitem"
              type="button"
              tabIndex={activeIndex === i ? 0 : -1}
              className="num w-full text-left px-2.5 py-1.5 text-[12px] hover:bg-black/5 focus:bg-black/5 focus:outline-none rounded-sm flex items-center gap-2"
              onClick={(e) => {
                e.preventDefault();
                void copy(f.key, f.noun);
              }}
            >
              {ICONS[f.key]}
              <span>Copy {f.noun}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
