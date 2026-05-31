"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  X,
  CaretLeft,
  CaretRight,
  Sparkle,
} from "@phosphor-icons/react/dist/ssr";
import {
  isOnboarded,
  markOnboarded,
  TOUR_STEPS,
} from "@/lib/onboarding";

// First-run tour. Auto-opens once per browser. Listeners on
// `shotclassify:show-tour` let other pages replay it on demand.

export default function OnboardingTour() {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!isOnboarded()) {
      // Defer one tick so the page paints first; the overlay then animates in.
      const t = setTimeout(() => setOpen(true), 250);
      return () => clearTimeout(t);
    }
  }, []);

  useEffect(() => {
    const handler = () => {
      setStep(0);
      setOpen(true);
    };
    window.addEventListener("shotclassify:show-tour", handler);
    return () => window.removeEventListener("shotclassify:show-tour", handler);
  }, []);

  const close = useCallback(() => {
    markOnboarded();
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight")
        setStep((s) => Math.min(TOUR_STEPS.length - 1, s + 1));
      else if (e.key === "ArrowLeft") setStep((s) => Math.max(0, s - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;
  const s = TOUR_STEPS[step];
  const last = step === TOUR_STEPS.length - 1;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="onb-title"
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
      style={{ background: "rgba(8, 12, 16, 0.55)" }}
      onClick={close}
    >
      <div
        className="w-full sm:w-[480px] max-w-full m-0 sm:m-4 rounded-t-2xl sm:rounded-2xl border shadow-2xl"
        style={{
          background: "var(--color-chalk)",
          borderColor: "var(--color-rule)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-5 py-3 border-b"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <div className="flex items-center gap-2">
            <Sparkle weight="duotone" size={18} />
            <span className="eyebrow">
              Step {step + 1} of {TOUR_STEPS.length}
            </span>
          </div>
          <button
            type="button"
            onClick={close}
            aria-label="Dismiss tour"
            className="p-1 rounded hover:bg-black/5"
          >
            <X weight="duotone" size={18} />
          </button>
        </div>

        <div className="px-5 py-5">
          <h2
            id="onb-title"
            className="h-display text-[20px] mb-2"
            style={{ letterSpacing: "-0.01em" }}
          >
            {s.title}
          </h2>
          <p className="text-[14px] leading-relaxed opacity-80">{s.body}</p>

          <div className="mt-4 flex items-center gap-2">
            {TOUR_STEPS.map((_, i) => (
              <span
                key={i}
                aria-hidden
                className="h-1 flex-1 rounded-full"
                style={{
                  background:
                    i === step
                      ? "var(--color-felt)"
                      : "var(--color-rule)",
                }}
              />
            ))}
          </div>
        </div>

        <div
          className="flex items-center justify-between gap-2 px-5 py-3 border-t"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setStep((x) => Math.max(0, x - 1))}
              disabled={step === 0}
              className="inline-flex items-center gap-1 text-[13px] px-2.5 py-1.5 rounded border disabled:opacity-40"
              style={{ borderColor: "var(--color-rule)" }}
            >
              <CaretLeft weight="duotone" size={14} /> Back
            </button>
            <button
              type="button"
              onClick={close}
              className="text-[12px] opacity-60 hover:opacity-100 underline underline-offset-2"
            >
              Skip
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href={s.cta.href}
              onClick={close}
              className="text-[13px] px-3 py-1.5 rounded font-medium"
              style={{
                background: "var(--color-felt)",
                color: "var(--color-chalk)",
              }}
            >
              {s.cta.label}
            </Link>
            {!last ? (
              <button
                type="button"
                onClick={() => setStep((x) => Math.min(TOUR_STEPS.length - 1, x + 1))}
                className="inline-flex items-center gap-1 text-[13px] px-2.5 py-1.5 rounded border"
                style={{ borderColor: "var(--color-rule)" }}
              >
                Next <CaretRight weight="duotone" size={14} />
              </button>
            ) : (
              <button
                type="button"
                onClick={close}
                className="text-[13px] px-2.5 py-1.5 rounded border"
                style={{ borderColor: "var(--color-rule)" }}
              >
                Done
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
