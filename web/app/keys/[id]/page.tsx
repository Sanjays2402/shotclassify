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
  Key,
  Lock,
  PencilSimple,
  Terminal,
  Trash,
  Warning,
} from "@phosphor-icons/react/dist/ssr";

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
  const width = 720;
  const padX = 8;
  const padY = 12;
  const max = Math.max(1, ...series.map((s) => s.count));
  const stepX =
    series.length > 1 ? (width - padX * 2) / (series.length - 1) : 0;
  const points = series.map((s, i) => {
    const x = padX + i * stepX;
    const y =
      padY + (height - padY * 2) * (1 - s.count / max);
    return { x, y, ...s };
  });
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(" ");
  const area = `${path} L ${(padX + (series.length - 1) * stepX).toFixed(
    1,
  )} ${height - padY} L ${padX.toFixed(1)} ${height - padY} Z`;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="w-full h-24"
      role="img"
      aria-label={`Daily request volume, peak ${max}`}
    >
      <path d={area} fill="currentColor" opacity="0.10" />
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {points.map((p, i) =>
        p.count > 0 ? (
          <circle key={i} cx={p.x} cy={p.y} r="2" fill="currentColor" />
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
  const [revealed, setRevealed] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

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
    if (
      !confirm(
        "Rotate this key? The current secret stops working immediately. You will see the new value once.",
      )
    )
      return;
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
    if (!confirm("Revoke this key? Calls using it will fail immediately."))
      return;
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
  const sampleCurl = useMemo(() => {
    const token = revealed ?? `${data?.key.prefix ?? "sk_live_"}…`;
    return `curl -X POST ${origin}/v1/classify \\
  -H "Authorization: Bearer ${token}" \\
  -F "file=@screenshot.png"`;
  }, [revealed, data, origin]);

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
              <button
                onClick={onRotate}
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
                onClick={onRevoke}
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

          {/* Curl */}
          <section
            className="rounded border p-5"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <div className="flex items-center justify-between">
              <div className="eyebrow flex items-center gap-1.5">
                <Terminal size={12} weight="duotone" />
                <span>Try it from your shell</span>
              </div>
              <button
                onClick={() => copy("curl", sampleCurl)}
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
            <pre
              className="mt-2 text-[12px] p-3 rounded overflow-x-auto"
              style={{ background: "rgba(0,0,0,0.04)" }}
            >
              <code>{sampleCurl}</code>
            </pre>
            {!revealed ? (
              <p
                className="mt-2 text-[11px]"
                style={{ color: "var(--color-ink-mute)" }}
              >
                The secret is hashed at rest, so the snippet shows the prefix.
                Rotate to mint a fresh one you can paste in.
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
