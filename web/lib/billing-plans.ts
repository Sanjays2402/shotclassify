// Public-safe slice of the billing module. Plans + types only. Safe to
// import from client components because it has no node: imports.
export type PlanId = "free" | "pro" | "team";

export type Plan = {
  id: PlanId;
  name: string;
  price_monthly_usd: number;
  blurb: string;
  features: string[];
  cta: string;
  highlight: boolean;
  limit_per_month: number;
};

export const PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    price_monthly_usd: 0,
    blurb: "Kick the tires. Real classifications, full history, share links.",
    features: [
      "200 classifications per month",
      "Full history with search and tags",
      "Public share links and OG preview",
      "1 API key, JSON and CSV export",
    ],
    cta: "Current plan",
    highlight: false,
    limit_per_month: 200,
  },
  {
    id: "pro",
    name: "Pro",
    price_monthly_usd: 29,
    blurb: "For builders shipping a classifier into their own product.",
    features: [
      "10,000 classifications per month",
      "Webhooks with retry and delivery log",
      "5 API keys, priority queue",
      "Email digest of activity",
    ],
    cta: "Upgrade to Pro",
    highlight: true,
    limit_per_month: 10_000,
  },
  {
    id: "team",
    name: "Team",
    price_monthly_usd: 99,
    blurb: "For squads that need shared history and per-seat keys.",
    features: [
      "100,000 classifications per month",
      "Unlimited API keys and webhooks",
      "Shared history across the workspace",
      "SSO and audit log export",
    ],
    cta: "Talk to us",
    highlight: false,
    limit_per_month: 100_000,
  },
];

export function getPlan(id: string): Plan | null {
  return PLANS.find((p) => p.id === id) ?? null;
}
