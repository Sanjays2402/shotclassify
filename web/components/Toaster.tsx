"use client";

// <Toaster> -- the single mount point that renders the app-wide toast stack.
// Drop one of these into the root layout; every `toast.success(...)` call
// anywhere in the tree shows up here. Replaces the per-page bespoke `flash` /
// `bulkFlash` confirmation banners.
//
// Visual language: chalk panel surface, felt-green / cue-yellow / red accent
// rail down the left edge keyed to the toast kind, mono eyebrow, dismiss X.
// Stacks bottom-right, slides up + fades in, respects prefers-reduced-motion.

import { useSyncExternalStore } from "react";
import {
  CheckCircle,
  Warning,
  Info,
  X,
} from "@phosphor-icons/react/dist/ssr";
import {
  toast as store,
  serverSnapshot,
  type Toast,
  type ToastKind,
} from "@/lib/toast-store";

const KIND_META: Record<
  ToastKind,
  { rail: string; icon: React.ReactNode; label: string }
> = {
  success: {
    rail: "var(--color-felt)",
    icon: <CheckCircle size={18} weight="duotone" />,
    label: "Success",
  },
  error: {
    rail: "#b91c1c",
    icon: <Warning size={18} weight="duotone" />,
    label: "Error",
  },
  info: {
    rail: "var(--color-cue-deep)",
    icon: <Info size={18} weight="duotone" />,
    label: "Heads up",
  },
};

function ToastCard({ t }: { t: Toast }) {
  const meta = KIND_META[t.kind];
  return (
    <div
      role={t.kind === "error" ? "alert" : "status"}
      className="panel sc-toast pointer-events-auto flex items-start gap-2.5 pl-3 pr-2 py-2.5 shadow-lg"
      style={{
        minWidth: 260,
        maxWidth: 380,
        borderLeft: `3px solid ${meta.rail}`,
      }}
      data-testid="toast"
      data-kind={t.kind}
    >
      <span className="mt-0.5 shrink-0" style={{ color: meta.rail }} aria-hidden>
        {meta.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="eyebrow" style={{ color: meta.rail }}>
          {meta.label}
        </div>
        <div className="text-[13px] leading-snug mt-0.5 break-words">
          {t.message}
        </div>
      </div>
      <button
        type="button"
        onClick={() => store.dismiss(t.id)}
        aria-label="Dismiss notification"
        className="shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-sm opacity-50 hover:opacity-100 transition-opacity"
      >
        <X size={13} weight="bold" />
      </button>
    </div>
  );
}

export default function Toaster() {
  const toasts = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    () => serverSnapshot,
  );

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed z-[120] bottom-4 right-4 flex flex-col-reverse gap-2 pointer-events-none"
      aria-live="polite"
      aria-label="Notifications"
      data-testid="toaster"
    >
      {toasts.map((t) => (
        <ToastCard key={t.id} t={t} />
      ))}
    </div>
  );
}
