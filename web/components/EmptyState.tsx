"use client";

// Reusable empty-state panel. The codebase reinvents this pattern across
// /shots, /webhooks, /notifications, and admin pages with subtly different
// type ramps and spacing. This is the canonical shape.
//
// Design language: chalk-cream surface, eyebrow ALL-CAPS label, h-display
// heading, monospace body sub-line. An optional icon slot (a Phosphor icon
// works great), and zero-to-two CTAs. The component is presentation-only;
// callers wire SWR/error state.

import type { ReactNode } from "react";

export type EmptyStateAction = {
  label: string;
  // EITHER provide `href` (renders as a Next-friendly <a>) OR `onClick`
  // (renders as <button>). Pass `kind="cue"` for the primary yellow CTA.
  href?: string;
  onClick?: () => void;
  kind?: "cue" | "ghost";
  external?: boolean;
};

export type EmptyStateProps = {
  // Tiny ALL-CAPS eyebrow above the heading. e.g. "Box score".
  eyebrow?: string;
  // The main headline. Short. Two to four words. h-display sized.
  title: string;
  // Sub-line. One sentence. Up to ~120 chars renders cleanly.
  body?: ReactNode;
  // An icon ReactNode -- a Phosphor icon, an emoji wrapper, or a logo glyph.
  // Renders in a circular felt-green well above the eyebrow.
  icon?: ReactNode;
  // Zero, one, or two actions. The first is rendered with the visual weight
  // implied by its `kind` (defaults to "ghost" for a single non-cue action,
  // "cue" for a single primary action when you pass kind: "cue").
  primary?: EmptyStateAction;
  secondary?: EmptyStateAction;
  // Variant. "panel" (default) renders inside a chalk panel with rounded
  // border -- drop into a card slot. "bare" omits the panel chrome so
  // callers that already wrap with `.panel` don't double up.
  variant?: "panel" | "bare";
  // Test id for component tests.
  "data-testid"?: string;
};

function ActionBtn({
  action,
  isPrimary,
}: {
  action: EmptyStateAction;
  isPrimary: boolean;
}) {
  // Default visual: primary inherits "cue" unless caller overrode, secondary
  // inherits ghost. Callers can still flip both.
  const kind =
    action.kind ??
    (isPrimary ? "cue" : "ghost");
  const cls = kind === "cue" ? "btn btn-cue" : "btn btn-ghost";

  if (action.href) {
    return (
      <a
        href={action.href}
        target={action.external ? "_blank" : undefined}
        rel={action.external ? "noopener noreferrer" : undefined}
        className={cls}
      >
        {action.label}
      </a>
    );
  }
  return (
    <button type="button" className={cls} onClick={action.onClick}>
      {action.label}
    </button>
  );
}

export function EmptyState({
  eyebrow,
  title,
  body,
  icon,
  primary,
  secondary,
  variant = "panel",
  "data-testid": testId,
}: EmptyStateProps) {
  const wrapClass =
    variant === "panel" ? "panel p-10 text-center" : "p-10 text-center";

  return (
    <div
      role="status"
      aria-live="polite"
      className={wrapClass}
      data-testid={testId}
    >
      {icon ? (
        <div
          className="mx-auto mb-4 inline-flex items-center justify-center rounded-full"
          style={{
            width: 56,
            height: 56,
            background:
              "linear-gradient(180deg, var(--color-felt) 0%, var(--color-felt-deep) 100%)",
            color: "var(--color-chalk)",
            boxShadow:
              "inset 0 1px 0 rgba(255,255,255,0.10), 0 4px 14px -6px rgba(7,48,30,0.45)",
          }}
          aria-hidden
        >
          {icon}
        </div>
      ) : null}
      {eyebrow ? <div className="eyebrow mb-2">{eyebrow}</div> : null}
      <h2 className="h-display text-[22px] md:text-[26px] leading-tight">
        {title}
      </h2>
      {body ? (
        <p className="text-[13px] opacity-75 mt-2 max-w-[52ch] mx-auto leading-relaxed">
          {body}
        </p>
      ) : null}
      {(primary || secondary) && (
        <div className="mt-5 flex items-center justify-center gap-2">
          {primary ? <ActionBtn action={primary} isPrimary /> : null}
          {secondary ? (
            <ActionBtn action={secondary} isPrimary={false} />
          ) : null}
        </div>
      )}
    </div>
  );
}

export default EmptyState;
