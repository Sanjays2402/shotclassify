// ConfBadge: a compact, semantically-colored confidence pill. Wherever the
// codebase renders a bare `pct(r.confidence)` number we'd rather see a
// pill that signals the confidence tier (high/mid/low) at a glance AND
// announces tier-aware copy to screen readers.
//
// Three sizes: sm (table cells), md (default), lg (detail header). Two
// variants: solid (filled background, white-ish text) and ghost (transparent
// background with a 1px tier-colored border, the colored text is its own
// hint). Solid is louder, ghost composes better next to other chips.

import {
  confAriaLabel,
  confDisplay,
  confTier,
  confTooltip,
  confTokenName,
} from "@/lib/confidence";

export type ConfBadgeProps = {
  score: number;
  size?: "sm" | "md" | "lg";
  variant?: "solid" | "ghost";
  // Override how many fraction digits the rendered % shows. Defaults to 0
  // at size=sm, 1 elsewhere -- packed cells stay tight, detail views read
  // more precise. Pass any int to override.
  digits?: number;
  // Optional className passthrough so consumers can adjust spacing.
  className?: string;
  // Override the tooltip title. Default uses confTooltip() output.
  title?: string;
};

export function ConfBadge({
  score,
  size = "md",
  variant = "ghost",
  digits,
  className,
  title,
}: ConfBadgeProps) {
  const tier = confTier(score);
  const token = confTokenName(score); // "--color-conf-high" etc.
  const dig = typeof digits === "number" ? digits : size === "sm" ? 0 : 1;
  const display = confDisplay(score, dig);
  const aria = confAriaLabel(score, dig);
  const tip = title ?? confTooltip(score);

  // Size scaling for the pill chrome -- compact rounded-sm chips, mono
  // tabular numerals so columns of badges line up.
  const sizeClasses =
    size === "sm"
      ? "text-[11px] px-1.5 py-[1px]"
      : size === "lg"
      ? "text-[16px] px-3 py-1"
      : "text-[12px] px-2 py-0.5";

  const baseClasses =
    "num inline-flex items-center gap-1 rounded-sm whitespace-nowrap leading-none transition-colors";

  const style =
    variant === "solid"
      ? {
          background: `var(${token})`,
          // For high (cue-yellow) and low (gray) the readable text is dark.
          // For mid (amber) dark text also reads fine.
          color: "var(--color-ink)",
        }
      : {
          color: `var(${token})`,
          background:
            tier === "high"
              ? "rgba(245, 197, 24, 0.12)"
              : tier === "mid"
              ? "rgba(224, 138, 30, 0.10)"
              : "rgba(107, 111, 107, 0.10)",
          border: `1px solid var(${token})`,
        };

  return (
    <span
      className={[baseClasses, sizeClasses, className].filter(Boolean).join(" ")}
      style={style}
      aria-label={aria}
      title={tip}
      data-tier={tier}
      data-testid="conf-badge"
    >
      <span
        className="inline-block rounded-full"
        style={{
          width: size === "sm" ? 5 : size === "lg" ? 8 : 6,
          height: size === "sm" ? 5 : size === "lg" ? 8 : 6,
          background: `var(${token})`,
        }}
        aria-hidden
      />
      <span>{display}</span>
    </span>
  );
}

export default ConfBadge;
