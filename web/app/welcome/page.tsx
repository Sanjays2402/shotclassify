import type { Metadata } from "next";
import Link from "next/link";
import {
  Sparkle,
  ImageSquare,
  ClockCounterClockwise,
  Key,
  ArrowRight,
} from "@phosphor-icons/react/dist/ssr";
import WelcomeStart from "@/components/WelcomeStart";
import { TOUR_STEPS } from "@/lib/onboarding";

export const metadata: Metadata = {
  title: "Welcome · ShotClassify",
  description:
    "Get started with ShotClassify in three steps: classify a screenshot, browse history, and call the API.",
};

const ICONS = [ImageSquare, ClockCounterClockwise, Key];

export default function WelcomePage() {
  return (
    <div className="flex flex-col gap-8 max-w-3xl mx-auto">
      <section className="felt p-6 md:p-8">
        <div className="flex items-center gap-2 mb-2">
          <Sparkle weight="duotone" size={18} />
          <span className="eyebrow">First run</span>
        </div>
        <h1
          className="h-display text-[28px] md:text-[34px] mb-3"
          style={{ letterSpacing: "-0.015em" }}
        >
          Welcome to ShotClassify
        </h1>
        <p className="text-[15px] leading-relaxed opacity-80 mb-5">
          ShotClassify turns any screenshot into a typed record. Drop an image,
          get a category, confidence scores, OCR text, and extracted fields.
          Here is the 90 second tour.
        </p>
        <WelcomeStart />
      </section>

      <ol className="flex flex-col gap-4">
        {TOUR_STEPS.map((s, i) => {
          const Icon = ICONS[i] ?? Sparkle;
          return (
            <li
              key={s.title}
              className="rounded-2xl border p-5 flex gap-4"
              style={{
                borderColor: "var(--color-rule)",
                background: "var(--color-chalk)",
              }}
            >
              <div
                className="shrink-0 w-10 h-10 rounded-xl flex items-center justify-center"
                style={{
                  background: "var(--color-felt)",
                  color: "var(--color-chalk)",
                }}
              >
                <Icon weight="duotone" size={22} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="eyebrow">Step {i + 1}</span>
                  <h2
                    className="h-display text-[17px]"
                    style={{ letterSpacing: "-0.01em" }}
                  >
                    {s.title}
                  </h2>
                </div>
                <p className="text-[14px] leading-relaxed opacity-80 mb-3">
                  {s.body}
                </p>
                <Link
                  href={s.cta.href}
                  className="inline-flex items-center gap-1.5 text-[13px] px-3 py-1.5 rounded border font-medium hover:bg-black/5"
                  style={{ borderColor: "var(--color-rule)" }}
                >
                  {s.cta.label} <ArrowRight weight="duotone" size={14} />
                </Link>
              </div>
            </li>
          );
        })}
      </ol>

      <div
        className="rounded-2xl border p-5"
        style={{
          borderColor: "var(--color-rule)",
          background: "var(--color-chalk)",
        }}
      >
        <h3 className="h-display text-[15px] mb-1">Already comfortable?</h3>
        <p className="text-[13px] opacity-70 mb-3">
          Jump straight in. You can replay this tour anytime from the Account
          page.
        </p>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/"
            className="text-[13px] px-3 py-1.5 rounded font-medium"
            style={{
              background: "var(--color-felt)",
              color: "var(--color-chalk)",
            }}
          >
            Go to Live
          </Link>
          <Link
            href="/demo"
            className="text-[13px] px-3 py-1.5 rounded border"
            style={{ borderColor: "var(--color-rule)" }}
          >
            Try the demo
          </Link>
        </div>
      </div>
    </div>
  );
}
