import type { Metadata } from "next";
import Link from "next/link";
import { Receipt, ArrowLeft } from "@phosphor-icons/react/dist/ssr";

import PricingClient from "@/components/PricingClient";

export const metadata: Metadata = {
  title: "Pricing · ShotClassify",
  description:
    "Plans for ShotClassify. Free tier for trying it, Pro for shipping it, Team for shared workspaces.",
};

export default function PricingPage() {
  return (
    <div className="flex flex-col gap-6 max-w-5xl mx-auto">
      <header className="flex flex-col gap-1">
        <div className="eyebrow flex items-center gap-2">
          <Receipt size={14} weight="duotone" /> Plans
        </div>
        <h1 className="h-display text-[34px]">PRICING</h1>
        <p className="text-[14px] opacity-75 max-w-2xl">
          Start free, upgrade when you outgrow the monthly ceiling. No card
          required to record interest. Stripe checkout lands next release.
        </p>
      </header>

      <PricingClient />

      <section className="panel p-5">
        <h2 className="h-display text-[16px] mb-2">FAQ</h2>
        <dl className="text-[13px] space-y-3 opacity-90">
          <div>
            <dt className="font-medium">What counts as a classification?</dt>
            <dd className="opacity-80">
              One image or one frame in a batch. Failed requests do not count
              against your quota.
            </dd>
          </div>
          <div>
            <dt className="font-medium">What happens when I hit the limit?</dt>
            <dd className="opacity-80">
              The <code className="kbd">/v1/classify</code> endpoint starts
              returning HTTP 402. Your history, exports, and share links keep
              working until the period resets.
            </dd>
          </div>
          <div>
            <dt className="font-medium">Can I cancel anytime?</dt>
            <dd className="opacity-80">
              Yes. Plans are month to month. When Stripe is live, cancellation
              takes effect at the end of the current period.
            </dd>
          </div>
        </dl>
      </section>

      <div className="text-[12px] opacity-70">
        <Link
          href="/usage"
          className="inline-flex items-center gap-1 hover:opacity-100"
        >
          <ArrowLeft size={12} weight="bold" /> Back to your usage
        </Link>
      </div>
    </div>
  );
}
