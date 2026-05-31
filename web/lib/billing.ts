// Plan catalog and upgrade-intent store.
//
// Stripe wiring is not in this release. Until then we record the user's
// stated intent to upgrade (which plan, when, optional company/email)
// so operators have a clear list of who to contact and so the UI can
// show a confirmation after the click instead of dead-ending. Storage
// is a tiny JSON file alongside notifications.json. No DB migration.
// Server-side billing operations: persistence + intent recording.
// Client components must import from ./billing-plans instead, which
// has no node: imports.
import { promises as fs } from "node:fs";
import path from "node:path";

import { PLANS, getPlan, type Plan, type PlanId } from "./billing-plans";

export { PLANS, getPlan };
export type { Plan, PlanId };

export type UpgradeIntent = {
  id: string;
  plan: PlanId;
  email: string | null;
  company: string | null;
  note: string | null;
  source: string;
  created_at: string;
};

export type IntentStore = {
  intents: UpgradeIntent[];
};

const ROOT =
  process.env.SHOTCLASSIFY_STORE_DIR ||
  path.join(process.cwd(), "..", "storage");
const STORE_PATH = path.join(ROOT, "billing_intents.json");

export function intentStorePath(): string {
  return STORE_PATH;
}

async function readStore(): Promise<IntentStore> {
  try {
    const raw = await fs.readFile(STORE_PATH, "utf8");
    const parsed = JSON.parse(raw) as Partial<IntentStore>;
    if (parsed && Array.isArray(parsed.intents)) {
      return { intents: parsed.intents.filter(isIntent) };
    }
    return { intents: [] };
  } catch (err: unknown) {
    const code = (err as { code?: string } | null)?.code;
    if (code === "ENOENT") return { intents: [] };
    return { intents: [] };
  }
}

function isIntent(v: unknown): v is UpgradeIntent {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.plan === "string" &&
    typeof o.created_at === "string"
  );
}

async function writeStore(store: IntentStore): Promise<void> {
  await fs.mkdir(path.dirname(STORE_PATH), { recursive: true });
  const tmp = `${STORE_PATH}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(store, null, 2), "utf8");
  await fs.rename(tmp, STORE_PATH);
}

export type RecordIntentInput = {
  plan: string;
  email?: string | null;
  company?: string | null;
  note?: string | null;
  source?: string | null;
};

export type RecordIntentResult =
  | { ok: true; intent: UpgradeIntent }
  | { ok: false; error: { code: string; message: string } };

function trimOrNull(v: unknown, max: number): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  if (!t) return null;
  return t.slice(0, max);
}

function looksLikeEmail(s: string): boolean {
  // Loose but practical: one @, no spaces, a dot somewhere after @.
  if (s.length > 254) return false;
  const at = s.indexOf("@");
  if (at <= 0 || at !== s.lastIndexOf("@")) return false;
  if (/\s/.test(s)) return false;
  const dom = s.slice(at + 1);
  return dom.includes(".") && dom.length >= 3;
}

function randomId(): string {
  // Short, URL-safe, no extra deps. 12 hex chars is plenty for an
  // operator-visible intent id.
  let out = "";
  for (let i = 0; i < 12; i++) {
    out += Math.floor(Math.random() * 16).toString(16);
  }
  return `int_${out}`;
}

export async function recordIntent(
  input: RecordIntentInput,
): Promise<RecordIntentResult> {
  const plan = getPlan(input.plan);
  if (!plan) {
    return {
      ok: false,
      error: { code: "unknown_plan", message: "Unknown plan id." },
    };
  }
  if (plan.id === "free") {
    return {
      ok: false,
      error: {
        code: "free_plan",
        message: "Free is the current default plan and needs no upgrade.",
      },
    };
  }
  const email = trimOrNull(input.email, 254);
  if (email && !looksLikeEmail(email)) {
    return {
      ok: false,
      error: { code: "bad_email", message: "Email is not a valid address." },
    };
  }
  const intent: UpgradeIntent = {
    id: randomId(),
    plan: plan.id,
    email,
    company: trimOrNull(input.company, 120),
    note: trimOrNull(input.note, 1000),
    source: trimOrNull(input.source, 64) ?? "pricing",
    created_at: new Date().toISOString(),
  };
  const store = await readStore();
  store.intents.push(intent);
  // Cap so a malicious caller cannot grow this file without bound.
  if (store.intents.length > 1000) {
    store.intents = store.intents.slice(-1000);
  }
  await writeStore(store);
  return { ok: true, intent };
}

export async function listIntents(): Promise<UpgradeIntent[]> {
  const store = await readStore();
  // Most recent first.
  return [...store.intents].sort((a, b) =>
    a.created_at < b.created_at ? 1 : -1,
  );
}
