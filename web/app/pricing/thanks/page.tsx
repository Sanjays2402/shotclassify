import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  CheckCircle,
  EnvelopeSimple,
  ArrowRight,
  Receipt,
} from "@phosphor-icons/react/dist/ssr";

import { getPlan } from "@/lib/billing-plans";

export const metadata: Metadata = {
  title: "Thanks · ShotClassify",
  description: "We recorded your upgrade interest.",
  robots: { index: false },
};

type Params = { searchParams: Promise<{ id?: string; plan?: string }> };

export default async function ThanksPage({ searchParams }: Params) {
  const { id, plan } = await searchParams;
  if (!id || !plan) notFound();
  const p = getPlan(plan);
  if (!p) notFound();
  return (
    <div className="flex flex-col gap-6 max-w-2xl mx-auto">
      <header>
        <div className="eyebrow flex items-center gap-2">
          <Receipt size={14} weight="duotone" /> Upgrade interest recorded
        </div>
        <h1 className="h-display text-[34px]">THANKS</h1>
      </header>

      <section className="panel p-6 flex flex-col gap-4">
        <div className="flex items-start gap-3">
          <CheckCircle
            size={28}
            weight="duotone"
            style={{ color: "var(--color-felt, #0f766e)" }}
          />
          <div>
            <h2 className="h-display text-[20px]">
              You are on the {p.name} waitlist
            </h2>
            <p className="text-[13px] opacity-75 mt-1">
              We will email a payment link the moment Stripe checkout goes
              live. Your reference id is{" "}
              <code className="kbd">{id}</code>.
            </p>
          </div>
        </div>

        <ul className="text-[13px] space-y-1.5 opacity-90">
          <li className="flex items-center gap-2">
            <EnvelopeSimple size={14} weight="duotone" /> Watch your inbox for
            the activation email.
          </li>
          <li className="flex items-center gap-2">
            <CheckCircle size={14} weight="duotone" /> Your free-tier
            classifications keep working in the meantime.
          </li>
        </ul>

        <div className="flex flex-wrap gap-2 pt-1">
          <Link
            href="/usage"
            className="btn inline-flex items-center gap-1.5"
          >
            Back to usage
            <ArrowRight size={14} weight="bold" />
          </Link>
          <Link
            href="/demo"
            className="btn btn-cue inline-flex items-center gap-1.5"
          >
            Keep classifying
            <ArrowRight size={14} weight="bold" />
          </Link>
        </div>
      </section>
    </div>
  );
}
