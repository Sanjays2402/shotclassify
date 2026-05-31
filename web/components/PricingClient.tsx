"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Lightning,
  CheckCircle,
  Sparkle,
  CircleNotch,
  Warning,
  ArrowRight,
  X,
} from "@phosphor-icons/react/dist/ssr";

import { PLANS, type Plan, type PlanId } from "@/lib/billing-plans";

type FlashKind = "ok" | "err";
type Flash = { kind: FlashKind; msg: string } | null;

function priceLabel(p: Plan): string {
  if (p.price_monthly_usd === 0) return "$0";
  return `$${p.price_monthly_usd}`;
}

export function PricingClient() {
  const router = useRouter();
  const [openPlan, setOpenPlan] = useState<PlanId | null>(null);
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);

  const reset = () => {
    setOpenPlan(null);
    setEmail("");
    setCompany("");
    setNote("");
    setFlash(null);
  };

  const submit = async (planId: PlanId) => {
    setBusy(true);
    setFlash(null);
    try {
      const res = await fetch("/api/billing/intent", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          plan: planId,
          email: email.trim() || null,
          company: company.trim() || null,
          note: note.trim() || null,
          source: "pricing",
        }),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => null)) as
          | { error?: { message?: string } }
          | null;
        throw new Error(j?.error?.message || `${res.status} ${res.statusText}`);
      }
      const j = (await res.json()) as { intent: { id: string } };
      router.push(`/pricing/thanks?id=${encodeURIComponent(j.intent.id)}&plan=${planId}`);
    } catch (e) {
      setFlash({
        kind: "err",
        msg: e instanceof Error ? e.message : "Could not record interest.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        role="list"
        aria-label="Plans"
      >
        {PLANS.map((p) => (
          <article
            key={p.id}
            role="listitem"
            className="panel p-5 flex flex-col gap-3"
            style={
              p.highlight
                ? {
                    borderColor: "var(--color-felt, #0f766e)",
                    boxShadow:
                      "0 0 0 1px var(--color-felt, #0f766e) inset",
                  }
                : undefined
            }
          >
            <div className="flex items-center gap-2">
              {p.highlight ? (
                <Lightning
                  size={20}
                  weight="duotone"
                  style={{ color: "var(--color-cue)" }}
                />
              ) : (
                <Sparkle size={20} weight="duotone" />
              )}
              <h3 className="h-display text-[18px]">{p.name}</h3>
            </div>
            <div className="font-mono text-[28px] tabular-nums">
              {priceLabel(p)}
              {p.price_monthly_usd > 0 && (
                <span className="text-[14px] opacity-60">/mo</span>
              )}
            </div>
            <p className="text-[13px] opacity-80">{p.blurb}</p>
            <ul className="text-[13px] space-y-1.5 opacity-90 flex-1">
              {p.features.map((f) => (
                <li key={f} className="flex items-start gap-2">
                  <CheckCircle
                    size={14}
                    weight="duotone"
                    className="shrink-0 mt-0.5"
                  />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            {p.id === "free" ? (
              <div className="text-[12px] opacity-60 mt-1">{p.cta}</div>
            ) : (
              <button
                type="button"
                className="btn btn-cue mt-1 inline-flex items-center justify-center gap-1.5"
                onClick={() => {
                  setOpenPlan(p.id);
                  setFlash(null);
                }}
                aria-haspopup="dialog"
                aria-expanded={openPlan === p.id}
              >
                {p.cta}
                <ArrowRight size={14} weight="bold" />
              </button>
            )}
          </article>
        ))}
      </div>

      {openPlan && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-3"
          role="dialog"
          aria-modal="true"
          aria-labelledby="intent-title"
          style={{ background: "rgba(0,0,0,0.45)" }}
          onClick={(e) => {
            if (e.target === e.currentTarget && !busy) reset();
          }}
        >
          <div
            className="panel p-5 w-full max-w-md flex flex-col gap-3"
            style={{ background: "var(--color-page, #fff)" }}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="eyebrow">Upgrade interest</div>
                <h2 id="intent-title" className="h-display text-[20px]">
                  {PLANS.find((p) => p.id === openPlan)?.name}
                </h2>
                <p className="text-[12px] opacity-70 mt-1">
                  Stripe checkout lands next release. Leave your email and we
                  will send a payment link as soon as it is live.
                </p>
              </div>
              <button
                type="button"
                className="rounded p-1 hover:opacity-70"
                aria-label="Close"
                onClick={reset}
                disabled={busy}
              >
                <X size={18} weight="bold" />
              </button>
            </div>

            <label className="flex flex-col gap-1 text-[12px]">
              <span className="eyebrow">Email (optional)</span>
              <input
                type="email"
                inputMode="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={busy}
                className="w-full rounded-md border px-3 py-2 text-[13px] bg-white outline-none focus:ring-2"
                style={{ borderColor: "var(--color-rule)" }}
                placeholder="you@company.com"
              />
            </label>

            <label className="flex flex-col gap-1 text-[12px]">
              <span className="eyebrow">Company (optional)</span>
              <input
                type="text"
                autoComplete="organization"
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                disabled={busy}
                className="w-full rounded-md border px-3 py-2 text-[13px] bg-white outline-none focus:ring-2"
                style={{ borderColor: "var(--color-rule)" }}
                placeholder="Acme"
              />
            </label>

            <label className="flex flex-col gap-1 text-[12px]">
              <span className="eyebrow">What do you need? (optional)</span>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={busy}
                className="w-full rounded-md border px-3 py-2 text-[13px] bg-white outline-none focus:ring-2 resize-none"
                style={{ borderColor: "var(--color-rule)" }}
                rows={3}
                placeholder="Volume, SLA, integrations..."
                maxLength={1000}
              />
            </label>

            {flash && (
              <div
                className="text-[12px] p-2 rounded-md flex items-start gap-2"
                role="alert"
                style={{
                  background:
                    flash.kind === "err"
                      ? "rgba(239,68,68,0.08)"
                      : "rgba(15,118,110,0.08)",
                  border:
                    flash.kind === "err"
                      ? "1px solid rgba(239,68,68,0.25)"
                      : "1px solid rgba(15,118,110,0.25)",
                }}
              >
                <Warning size={14} weight="duotone" className="shrink-0 mt-0.5" />
                <span>{flash.msg}</span>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                className="btn"
                onClick={reset}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-cue inline-flex items-center gap-1.5"
                onClick={() => submit(openPlan)}
                disabled={busy}
              >
                {busy ? (
                  <>
                    <CircleNotch
                      size={14}
                      weight="bold"
                      className="animate-spin"
                    />
                    Sending
                  </>
                ) : (
                  <>
                    Notify me
                    <ArrowRight size={14} weight="bold" />
                  </>
                )}
              </button>
            </div>

            <div className="text-[11px] opacity-60">
              No card needed. We only store what you type here plus a
              timestamp. <Link href="/account" className="underline">Manage your data</Link>.
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default PricingClient;
