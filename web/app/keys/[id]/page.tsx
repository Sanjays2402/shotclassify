"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowsClockwise,
  Check,
  ChartLineUp,
  Copy,
  Globe,
  Key,
  Lock,
  PencilSimple,
  Plus,
  Terminal,
  Trash,
  Warning,
  ListMagnifyingGlass,
  CircleNotch,
} from "@phosphor-icons/react/dist/ssr";
import { sparklineGeometry, summarizeSeries, peakPointIndex } from "@/lib/key-sparkline";
import {
  buildSnippet,
  SNIPPET_LANGS,
  type SnippetLang,
} from "@/lib/key-snippet";
import {
  readSnippetLang,
  writeSnippetLang,
  KEY_SNIPPET_LANG_DEFAULT,
} from "@/lib/key-snippet-pref";
import { SnippetLangToggle } from "@/components/SnippetLangToggle";
import { KEYS_CREATE_HREF } from "@/lib/key-trial";
import {
  isArmed,
  confirmLabel,
  confirmPrompt,
  nextOnTrigger,
  type KeyConfirmPending,
} from "@/lib/key-confirm";

type KeyScope = "read" | "write" | "admin";

type KeyDetail = {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  usage_count: number;
  rotated_at?: string | null;
  scopes?: KeyScope[];
  allowed_cidrs?: string[];
  daily_usage?: Record<string, number>;
};

type DetailResponse = {
  key: KeyDetail;
  usage: {
    window_days: number;
    series: { day: string; count: number }[];
    total: number;
  };
};

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtShortDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function Sparkline({
  series,
  height = 96,
}: {
  series: { day: string; count: number }[];
  height?: number;
}) {
  // Geometry + peak now come from the tested lib/key-sparkline helper so the
  // empty / single-point / all-zero edges can't regress in the inline SVG.
  const g = sparklineGeometry(series, { height });
  // Accent the busiest day's dot (F158) so the eye lands on the peak the
  // caption names, reusing the same first-peak tie-break as summarizeSeries.
  const peakIdx = peakPointIndex(g);
  return (
    <svg
      viewBox={`0 0 720 ${height}`}
      preserveAspectRatio="none"
      className="w-full h-24"
      role="img"
      aria-label={`Daily request volume, peak ${g.peak}`}
    >
      <path d={g.areaPath} fill="currentColor" opacity="0.10" />
      <path
        d={g.linePath}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {g.points.map((p, i) =>
        p.count > 0 ? (
          i === peakIdx ? (
            <circle key={i} cx={p.x} cy={p.y} r="3.5" fill="var(--color-cue-deep, #9a7a0a)" stroke="currentColor" strokeWidth="1">
              <title>{`Peak ${p.count} on ${p.day}`}</title>
            </circle>
          ) : (
            <circle key={i} cx={p.x} cy={p.y} r="2" fill="currentColor" />
          )
        ) : null,
      )}
    </svg>
  );
}

export default function KeyDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = typeof params?.id === "string" ? params.id : "";

  const [data, setData] = useState<DetailResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingName, setSavingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  // Inline two-step destructive confirm (F143) replaces confirm() — same state
  // machine as the /keys list (F136) so rotate/revoke match across surfaces.
  const [pendingConfirm, setPendingConfirm] = useState<KeyConfirmPending>(null);
  const [revealed, setRevealed] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  // Snippet language for the "Try it" block, persisted across visits + shared
  // with /keys (F141) so a Python shop sees Python on both surfaces. SSR opens
  // on the default, then the mount effect fills the saved choice.
  const [snippetLang, setSnippetLang] = useState<SnippetLang>(
    KEY_SNIPPET_LANG_DEFAULT,
  );
  useEffect(() => setSnippetLang(readSnippetLang()), []);
  const chooseSnippetLang = useCallback((lang: SnippetLang) => {
    setSnippetLang(lang);
    writeSnippetLang(lang);
  }, []);

  // IP allowlist editor state. `cidrDraft` holds the in-progress text, the
  // committed list comes from `data.key.allowed_cidrs`. Empty list = no
  // restriction (legacy behaviour).
  const [cidrDraft, setCidrDraft] = useState<string[]>([]);
  const [cidrInput, setCidrInput] = useState("");
  const [cidrSaving, setCidrSaving] = useState(false);
  const [cidrError, setCidrError] = useState<string | null>(null);
  const [cidrFlash, setCidrFlash] = useState<string | null>(null);

  // Activity feed: per-key audit timeline pulled from the API. Mutating
  // calls only (the audit log does not record GETs by design). Tenant
  // scoping and admin/read:audit enforcement happen in FastAPI.
  type ActivityEvent = {
    id: string;
    created_at: string | null;
    principal: string;
    method: string;
    path: string;
    status_code: number;
    client_ip: string | null;
    request_id: string | null;
    elapsed_ms: number;
  };
  type ActivityResponse = {
    key_id: string;
    label: string;
    tenant_id: string | null;
    limit: number;
    count: number;
    events: ActivityEvent[];
  };
  const [activity, setActivity] = useState<ActivityResponse | null>(null);
  const [activityErr, setActivityErr] = useState<string | null>(null);
  const [activityLoading, setActivityLoading] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const r = await fetch(`/api/keys/${encodeURIComponent(id)}?days=30`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (r.status === 404) {
        setErr("This key no longer exists.");
        setData(null);
        return;
      }
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const j: DetailResponse = await r.json();
      setData(j);
      setNameDraft(j.key.name);
      setErr(null);
    } catch (e: any) {
      setErr(e?.message || "Failed to load key.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const loadActivity = useCallback(async () => {
    if (!id) return;
    setActivityLoading(true);
    setActivityErr(null);
    try {
      const r = await fetch(
        `/api/keys/${encodeURIComponent(id)}/activity?limit=50`,
        { credentials: "same-origin", cache: "no-store" },
      );
      if (r.status === 401 || r.status === 403) {
        setActivityErr("You need the admin role to view this key's activity.");
        setActivity(null);
        return;
      }
      if (r.status === 404) {
        setActivityErr("Activity is not available for this key.");
        setActivity(null);
        return;
      }
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const j: ActivityResponse = await r.json();
      setActivity(j);
    } catch (e: any) {
      setActivityErr(e?.message || "Failed to load activity.");
    } finally {
      setActivityLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadActivity();
  }, [loadActivity]);

  const cidrCommitted = useMemo(
    () => data?.key.allowed_cidrs ?? [],
    [data],
  );
  const cidrDirty = useMemo(() => {
    if (cidrDraft.length !== cidrCommitted.length) return true;
    for (let i = 0; i < cidrDraft.length; i++) {
      if (cidrDraft[i] !== cidrCommitted[i]) return true;
    }
    return false;
  }, [cidrDraft, cidrCommitted]);

  // Keep the editor in sync with whatever the server last confirmed.
  useEffect(() => {
    setCidrDraft(cidrCommitted);
    setCidrError(null);
  }, [cidrCommitted]);

  const onAddCidr = useCallback(() => {
    const raw = cidrInput.trim();
    if (!raw) return;
    // Light client-side shape check; server canonicalizes and rejects bad input.
    const looksLikeIp = /^[0-9a-fA-F:.]+(\/\d{1,3})?$/.test(raw);
    if (!looksLikeIp) {
      setCidrError(
        "Not a valid IP or CIDR. Use forms like 203.0.113.4 or 2001:db8::/32.",
      );
      return;
    }
    if (cidrDraft.includes(raw)) {
      setCidrError("That entry is already in the list.");
      return;
    }
    setCidrError(null);
    setCidrDraft((prev) => [...prev, raw]);
    setCidrInput("");
  }, [cidrInput, cidrDraft]);

  const onRemoveCidr = useCallback((entry: string) => {
    setCidrError(null);
    setCidrDraft((prev) => prev.filter((e) => e !== entry));
  }, []);

  const onSaveCidrs = useCallback(
    async (next: string[]) => {
      if (!id) return;
      setCidrSaving(true);
      setCidrError(null);
      setCidrFlash(null);
      try {
        const r = await fetch(`/api/keys/${encodeURIComponent(id)}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ allowed_cidrs: next }),
        });
        if (!r.ok) {
          let msg = `${r.status} ${r.statusText}`;
          try {
            const j = await r.json();
            if (j?.error?.message) msg = j.error.message;
          } catch {}
          throw new Error(msg);
        }
        await load();
        setCidrFlash(
          next.length === 0
            ? "Allowlist cleared. Any source IP can use this key."
            : `Allowlist saved. ${next.length} entr${next.length === 1 ? "y" : "ies"} active.`,
        );
      } catch (e: any) {
        setCidrError(e?.message || "Failed to save allowlist.");
      } finally {
        setCidrSaving(false);
      }
    },
    [id, load],
  );

  const onSaveName = useCallback(async () => {
    if (!data) return;
    const clean = nameDraft.trim();
    if (!clean || clean === data.key.name) {
      setEditing(false);
      setNameDraft(data.key.name);
      return;
    }
    setSavingName(true);
    try {
      const r = await fetch(`/api/keys/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: clean }),
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t || `${r.status}`);
      }
      setEditing(false);
      await load();
    } catch (e: any) {
      setErr(e?.message || "Rename failed.");
    } finally {
      setSavingName(false);
    }
  }, [data, id, load, nameDraft]);

  const onToggleScope = useCallback(
    async (scope: KeyScope, present: boolean) => {
      if (!data) return;
      const current = new Set<KeyScope>(data.key.scopes ?? ["read", "write"]);
      if (present) current.delete(scope);
      else current.add(scope);
      // mirror server-side normalize: admin implies write implies read
      if (current.has("admin")) current.add("write");
      if (current.has("write")) current.add("read");
      const next = Array.from(current);
      if (next.length === 0) return; // require at least one
      try {
        const r = await fetch(`/api/keys/${encodeURIComponent(id)}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ scopes: next }),
        });
        if (!r.ok) throw new Error(`${r.status}`);
        await load();
      } catch (e: any) {
        setErr(e?.message || "Scope update failed.");
      }
    },
    [data, id, load],
  );

  const onRotate = useCallback(async () => {
    setRotating(true);
    setErr(null);
    try {
      const r = await fetch(
        `/api/keys/${encodeURIComponent(id)}/rotate`,
        { method: "POST" },
      );
      if (!r.ok) throw new Error(`${r.status}`);
      const j = await r.json();
      setRevealed(j.plaintext);
      await load();
    } catch (e: any) {
      setErr(e?.message || "Rotate failed.");
    } finally {
      setRotating(false);
    }
  }, [id, load]);

  const onRevoke = useCallback(async () => {
    setRevoking(true);
    try {
      const r = await fetch(`/api/keys/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (!r.ok) throw new Error(`${r.status}`);
      router.push("/keys");
    } catch (e: any) {
      setErr(e?.message || "Revoke failed.");
      setRevoking(false);
    }
  }, [id, router]);

  // Two-step: first click arms (inline prompt), Confirm fires (F143). Cancel
  // clears. Only one of rotate/revoke can be armed at a time.
  const triggerConfirm = useCallback(
    (action: "rotate" | "revoke") => {
      setPendingConfirm((prev) => {
        const { fire, pending } = nextOnTrigger(prev, action, id);
        if (fire) {
          if (action === "rotate") onRotate();
          else onRevoke();
        }
        return pending;
      });
    },
    [id, onRotate, onRevoke],
  );

  const copy = useCallback(async (slot: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(slot);
      setTimeout(() => setCopied((c) => (c === slot ? null : c)), 1500);
    } catch {
      /* ignore */
    }
  }, []);

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  // Shared snippet builder (F141) — the revealed-once rotation secret feeds the
  // real token; otherwise the placeholder. curl / Python / JavaScript stay in
  // lockstep with the /keys list because both call buildSnippet.
  const sampleSnippet = useMemo(
    () => buildSnippet(snippetLang, origin, revealed),
    [snippetLang, origin, revealed],
  );

  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/keys"
          className="inline-flex items-center gap-1.5 text-[12px]"
          style={{ color: "var(--color-ink-mute)" }}
        >
          <ArrowLeft size={14} weight="duotone" />
          All keys
        </Link>
      </div>

      {loading ? (
        <KeySkeleton />
      ) : err && !data ? (
        <div
          className="rounded border p-6 text-[13px] flex items-start gap-3"
          style={{
            borderColor: "var(--color-rule)",
            color: "var(--color-ink-mute)",
          }}
        >
          <Warning
            size={18}
            weight="duotone"
            style={{ color: "var(--color-warn, #d97706)" }}
          />
          <div>
            <div className="font-medium" style={{ color: "var(--color-ink)" }}>
              {err}
            </div>
            <div className="mt-1">
              It may have been revoked. Head back to{" "}
              <Link href="/keys" className="underline">
                /keys
              </Link>{" "}
              to issue a new one.
            </div>
          </div>
        </div>
      ) : data ? (
        <>
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="eyebrow flex items-center gap-1.5">
                <Key size={12} weight="duotone" />
                <span>API key</span>
              </div>
              {editing ? (
                <div className="mt-1 flex items-center gap-2">
                  <input
                    autoFocus
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") onSaveName();
                      if (e.key === "Escape") {
                        setEditing(false);
                        setNameDraft(data.key.name);
                      }
                    }}
                    className="h-display text-[28px] tracking-tight bg-transparent border-b outline-none"
                    style={{ borderColor: "var(--color-rule)" }}
                    maxLength={80}
                  />
                  <button
                    onClick={onSaveName}
                    disabled={savingName}
                    className="btn btn-cue text-[12px]"
                  >
                    Save
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setEditing(true)}
                  className="mt-1 flex items-center gap-2 group"
                >
                  <h1 className="h-display text-[28px] tracking-tight truncate">
                    {data.key.name}
                  </h1>
                  <PencilSimple
                    size={14}
                    weight="duotone"
                    className="opacity-0 group-hover:opacity-100 transition"
                    style={{ color: "var(--color-ink-mute)" }}
                  />
                </button>
              )}
              <div
                className="text-[12px] mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 tabular-nums"
                style={{ color: "var(--color-ink-mute)" }}
              >
                <span>Prefix {data.key.prefix}…</span>
                <span>•</span>
                <span>Created {fmtDate(data.key.created_at)}</span>
                <span>•</span>
                <span>Last used {fmtDate(data.key.last_used_at)}</span>
                {data.key.rotated_at ? (
                  <>
                    <span>•</span>
                    <span>Rotated {fmtDate(data.key.rotated_at)}</span>
                  </>
                ) : null}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {(() => {
                const rotateArmed = isArmed(pendingConfirm, "rotate", id);
                const revokeArmed = isArmed(pendingConfirm, "revoke", id);
                const armed = rotateArmed ? "rotate" : revokeArmed ? "revoke" : null;
                if (armed) {
                  return (
                    <div className="flex items-center gap-2 flex-wrap justify-end">
                      <span
                        className="text-[11px] max-w-[22rem]"
                        style={{ color: "var(--color-ink-mute)" }}
                      >
                        {confirmPrompt(armed)}
                      </span>
                      <button
                        onClick={() => triggerConfirm(armed)}
                        disabled={rotating || revoking}
                        className="btn text-[12px] inline-flex items-center gap-1.5 text-white disabled:opacity-50"
                        style={{ background: "var(--color-danger, #b91c1c)" }}
                        aria-label={`Confirm ${armed}`}
                      >
                        {armed === "rotate" ? (
                          <ArrowsClockwise size={14} weight="duotone" />
                        ) : (
                          <Trash size={14} weight="duotone" />
                        )}
                        {confirmLabel(armed, true)}
                      </button>
                      <button
                        onClick={() => setPendingConfirm(null)}
                        className="btn text-[12px]"
                        style={{
                          background: "transparent",
                          borderColor: "var(--color-rule)",
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  );
                }
                return (
                  <>
                    <button
                      onClick={() => triggerConfirm("rotate")}
                      disabled={rotating}
                      className="btn text-[12px] inline-flex items-center gap-1.5"
                      style={{
                        background: "transparent",
                        borderColor: "var(--color-rule)",
                      }}
                    >
                      <ArrowsClockwise size={14} weight="duotone" />
                      {rotating ? "Rotating…" : "Rotate"}
                    </button>
                    <button
                      onClick={() => triggerConfirm("revoke")}
                      disabled={revoking}
                      className="btn text-[12px] inline-flex items-center gap-1.5"
                      style={{
                        background: "transparent",
                        borderColor: "var(--color-rule)",
                        color: "var(--color-danger, #b91c1c)",
                      }}
                    >
                      <Trash size={14} weight="duotone" />
                      Revoke
                    </button>
                  </>
                );
              })()}
            </div>
          </header>

          {err ? (
            <div
              className="rounded border px-3 py-2 text-[12px] flex items-center gap-2"
              style={{
                borderColor: "var(--color-rule)",
                color: "var(--color-danger, #b91c1c)",
              }}
            >
              <Warning size={14} weight="duotone" />
              {err}
            </div>
          ) : null}

          {revealed ? (
            <div
              className="rounded border p-4"
              style={{ borderColor: "var(--color-rule)" }}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-[12px] font-medium">
                  New secret — copy now, it will not be shown again
                </div>
                <button
                  onClick={() => copy("rotated", revealed)}
                  className="text-[12px] inline-flex items-center gap-1.5"
                  style={{ color: "var(--color-ink-mute)" }}
                >
                  {copied === "rotated" ? (
                    <>
                      <Check size={14} weight="duotone" /> Copied
                    </>
                  ) : (
                    <>
                      <Copy size={14} weight="duotone" /> Copy
                    </>
                  )}
                </button>
              </div>
              <code className="mt-2 block text-[12px] break-all p-2 rounded bg-black/5">
                {revealed}
              </code>
            </div>
          ) : null}

          {/* Usage */}
          <section
            className="rounded border p-5"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <div className="flex items-end justify-between mb-3 gap-4 flex-wrap">
              <div>
                <div className="eyebrow flex items-center gap-1.5">
                  <ChartLineUp size={12} weight="duotone" />
                  <span>Last {data.usage.window_days} days</span>
                </div>
                <div className="text-[22px] tabular-nums mt-0.5">
                  {data.usage.total.toLocaleString()} requests
                </div>
              </div>
              <div
                className="text-[12px] tabular-nums"
                style={{ color: "var(--color-ink-mute)" }}
              >
                Lifetime {data.key.usage_count.toLocaleString()}
              </div>
            </div>
            {data.usage.total === 0 ? (
              <div
                className="rounded border border-dashed p-6 text-center text-[13px]"
                style={{
                  borderColor: "var(--color-rule)",
                  color: "var(--color-ink-mute)",
                }}
              >
                No requests yet. Use the snippet below to fire the first call.
              </div>
            ) : (
              <>
                <div style={{ color: "var(--color-cue, #3b82f6)" }}>
                  <Sparkline series={data.usage.series} />
                </div>
                <div
                  className="mt-2 flex justify-between text-[10px] tabular-nums"
                  style={{ color: "var(--color-ink-mute)" }}
                >
                  <span>{fmtShortDay(data.usage.series[0]?.day ?? "")}</span>
                  {(() => {
                    const s = summarizeSeries(data.usage.series);
                    return s.busiestDay ? (
                      <span>
                        Peak {s.peak} on {fmtShortDay(s.busiestDay)}
                      </span>
                    ) : null;
                  })()}
                  <span>
                    {fmtShortDay(
                      data.usage.series[data.usage.series.length - 1]?.day ??
                        "",
                    )}
                  </span>
                </div>
              </>
            )}
          </section>

          {/* Scopes */}
          <section
            className="rounded border p-5"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <div className="eyebrow flex items-center gap-1.5">
              <Lock size={12} weight="duotone" />
              <span>Scopes</span>
            </div>
            <p
              className="text-[12px] mt-1"
              style={{ color: "var(--color-ink-mute)" }}
            >
              Read covers GET endpoints. Write covers POST /v1/classify and
              implies read. Admin is required to register or delete webhooks
              and implies write.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {(["read", "write", "admin"] as KeyScope[]).map((scope) => {
                const has = (data.key.scopes ?? ["read", "write"]).includes(
                  scope,
                );
                return (
                  <button
                    key={scope}
                    onClick={() => onToggleScope(scope, has)}
                    className="text-[12px] px-2.5 py-1 rounded border inline-flex items-center gap-1.5"
                    style={{
                      borderColor: "var(--color-rule)",
                      background: has
                        ? "var(--color-cue, #3b82f6)"
                        : "transparent",
                      color: has ? "white" : "var(--color-ink)",
                    }}
                    aria-pressed={has}
                  >
                    {has ? <Check size={12} weight="duotone" /> : null}
                    {scope}
                  </button>
                );
              })}
            </div>
          </section>

          {/* IP allowlist */}
          <section
            className="rounded border p-5"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <div className="eyebrow flex items-center gap-1.5">
              <Globe size={12} weight="duotone" />
              <span>Source IP allowlist</span>
            </div>
            <p
              className="text-[12px] mt-1"
              style={{ color: "var(--color-ink-mute)" }}
            >
              Restrict this key to specific source IPs or CIDR ranges. Leave
              empty to accept from any IP. Use this for CI runners, a corporate
              egress range, or a single bastion. Both IPv4 and IPv6 accepted,
              with or without a /N suffix.
            </p>

            <div className="mt-3 flex flex-wrap gap-2" aria-label="Current allowlist">
              {cidrDraft.length === 0 ? (
                <span
                  className="text-[12px] px-2 py-1 rounded border"
                  style={{
                    borderColor: "var(--color-rule)",
                    color: "var(--color-ink-mute)",
                  }}
                >
                  No restriction. Any IP can use this key.
                </span>
              ) : (
                cidrDraft.map((entry) => (
                  <span
                    key={entry}
                    className="text-[12px] px-2 py-1 rounded border inline-flex items-center gap-1.5"
                    style={{ borderColor: "var(--color-rule)" }}
                  >
                    <code>{entry}</code>
                    <button
                      type="button"
                      aria-label={`Remove ${entry}`}
                      onClick={() => onRemoveCidr(entry)}
                      className="inline-flex"
                      style={{ color: "var(--color-ink-mute)" }}
                    >
                      <Trash size={12} weight="duotone" />
                    </button>
                  </span>
                ))
              )}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input
                type="text"
                value={cidrInput}
                onChange={(e) => setCidrInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    onAddCidr();
                  }
                }}
                placeholder="203.0.113.0/24 or 2001:db8::/32"
                aria-label="New IP or CIDR"
                className="text-[12px] px-2 py-1 rounded border min-w-[18rem]"
                style={{
                  borderColor: "var(--color-rule)",
                  background: "transparent",
                  color: "var(--color-ink)",
                }}
              />
              <button
                type="button"
                onClick={onAddCidr}
                disabled={!cidrInput.trim()}
                className="text-[12px] px-2.5 py-1 rounded border inline-flex items-center gap-1.5 disabled:opacity-50"
                style={{ borderColor: "var(--color-rule)" }}
              >
                <Plus size={12} weight="duotone" /> Add
              </button>
              <button
                type="button"
                onClick={() => onSaveCidrs(cidrDraft)}
                disabled={!cidrDirty || cidrSaving}
                className="text-[12px] px-2.5 py-1 rounded inline-flex items-center gap-1.5 disabled:opacity-50"
                style={{
                  background: "var(--color-cue, #3b82f6)",
                  color: "white",
                }}
              >
                {cidrSaving ? "Saving..." : "Save allowlist"}
              </button>
              {cidrDraft.length > 0 ? (
                <button
                  type="button"
                  onClick={() => onSaveCidrs([])}
                  disabled={cidrSaving}
                  className="text-[12px] px-2.5 py-1 rounded border inline-flex items-center gap-1.5 disabled:opacity-50"
                  style={{ borderColor: "var(--color-rule)", color: "var(--color-ink-mute)" }}
                >
                  Clear restriction
                </button>
              ) : null}
            </div>

            {cidrError ? (
              <p className="mt-2 text-[12px]" style={{ color: "#b91c1c" }}>
                {cidrError}
              </p>
            ) : null}
            {cidrFlash ? (
              <p
                className="mt-2 text-[12px]"
                style={{ color: "var(--color-ink-mute)" }}
              >
                {cidrFlash}
              </p>
            ) : null}
          </section>

          {/* Activity */}
          <section
            className="rounded border p-5"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="eyebrow flex items-center gap-1.5">
                  <ListMagnifyingGlass size={12} weight="duotone" />
                  <span>Recent activity</span>
                </div>
                <p
                  className="mt-1 text-[12px]"
                  style={{ color: "var(--color-ink-mute)" }}
                >
                  State changing calls signed by this key, from the
                  tamper evident audit log. Read only calls are not recorded.
                </p>
              </div>
              <button
                type="button"
                onClick={loadActivity}
                disabled={activityLoading}
                className="text-[12px] inline-flex items-center gap-1.5 px-2 py-1 rounded border"
                style={{
                  borderColor: "var(--color-rule)",
                  color: "var(--color-ink-mute)",
                }}
                aria-label="Refresh activity"
              >
                {activityLoading ? (
                  <CircleNotch size={12} weight="duotone" className="animate-spin" />
                ) : (
                  <ArrowsClockwise size={12} weight="duotone" />
                )}
                <span>Refresh</span>
              </button>
            </div>

            <div className="mt-4">
              {activityErr ? (
                <div
                  className="text-[12px] rounded border p-3"
                  style={{
                    borderColor: "var(--color-rule)",
                    color: "#b91c1c",
                  }}
                  role="alert"
                >
                  {activityErr}
                </div>
              ) : activityLoading && !activity ? (
                <div className="space-y-2" aria-hidden="true">
                  {[0, 1, 2, 3].map((i) => (
                    <div
                      key={i}
                      className="h-9 rounded animate-pulse"
                      style={{ background: "var(--color-rule)" }}
                    />
                  ))}
                </div>
              ) : activity && activity.events.length > 0 ? (
                <div
                  className="overflow-x-auto rounded border"
                  style={{ borderColor: "var(--color-rule)" }}
                >
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr style={{ color: "var(--color-ink-mute)" }}>
                        <th className="text-left font-normal px-3 py-2">When</th>
                        <th className="text-left font-normal px-3 py-2">Method</th>
                        <th className="text-left font-normal px-3 py-2">Path</th>
                        <th className="text-left font-normal px-3 py-2">Status</th>
                        <th className="text-left font-normal px-3 py-2 hidden sm:table-cell">IP</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activity.events.map((e) => (
                        <tr
                          key={e.id}
                          className="border-t"
                          style={{ borderColor: "var(--color-rule)" }}
                        >
                          <td className="px-3 py-2 whitespace-nowrap">
                            {fmtDate(e.created_at)}
                          </td>
                          <td className="px-3 py-2 font-mono">{e.method}</td>
                          <td
                            className="px-3 py-2 font-mono break-all"
                            title={e.request_id ?? undefined}
                          >
                            {e.path}
                          </td>
                          <td
                            className="px-3 py-2 font-mono"
                            style={{
                              color:
                                e.status_code >= 500
                                  ? "#b91c1c"
                                  : e.status_code >= 400
                                    ? "#a16207"
                                    : "inherit",
                            }}
                          >
                            {e.status_code}
                          </td>
                          <td className="px-3 py-2 font-mono hidden sm:table-cell">
                            {e.client_ip ?? "\u2014"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div
                  className="text-[12px] rounded border p-4 text-center"
                  style={{
                    borderColor: "var(--color-rule)",
                    color: "var(--color-ink-mute)",
                  }}
                >
                  No activity yet. Once this key makes a state changing call
                  it will appear here within seconds.
                </div>
              )}
            </div>
            {activity ? (
              <p
                className="mt-3 text-[11px]"
                style={{ color: "var(--color-ink-mute)" }}
              >
                Showing the {activity.count} most recent of up to {activity.limit}
                . Full history is available via the workspace audit log.
              </p>
            ) : null}
          </section>

          {/* Try it */}
          <section
            className="rounded border p-5"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="eyebrow flex items-center gap-1.5">
                <Terminal size={12} weight="duotone" />
                <span>Try it from your code</span>
              </div>
              <div className="flex items-center gap-2">
                <SnippetLangToggle value={snippetLang} onChange={chooseSnippetLang} />
                <button
                  onClick={() => copy("curl", sampleSnippet)}
                  className="text-[12px] inline-flex items-center gap-1.5"
                  style={{ color: "var(--color-ink-mute)" }}
                >
                  {copied === "curl" ? (
                    <>
                      <Check size={14} weight="duotone" /> Copied
                    </>
                  ) : (
                    <>
                      <Copy size={14} weight="duotone" /> Copy
                    </>
                  )}
                </button>
              </div>
            </div>
            <pre
              className="mt-2 text-[12px] p-3 rounded overflow-x-auto"
              style={{ background: "rgba(0,0,0,0.04)" }}
            >
              <code>{sampleSnippet}</code>
            </pre>
            {!revealed ? (
              <p
                className="mt-2 text-[11px]"
                style={{ color: "var(--color-ink-mute)" }}
              >
                The secret is hashed at rest, so the snippet shows the prefix.
                Rotate to mint a fresh one you can paste in.{" "}
                <Link
                  href={KEYS_CREATE_HREF}
                  className="underline underline-offset-2"
                  style={{ color: "var(--color-felt)" }}
                >
                  Generate one above
                </Link>
                .
              </p>
            ) : null}
          </section>
        </>
      ) : null}
    </div>
  );
}

function KeySkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div
        className="h-8 w-64 rounded"
        style={{ background: "var(--color-rule)" }}
      />
      <div
        className="h-32 rounded"
        style={{ background: "var(--color-rule)" }}
      />
      <div
        className="h-20 rounded"
        style={{ background: "var(--color-rule)" }}
      />
    </div>
  );
}
