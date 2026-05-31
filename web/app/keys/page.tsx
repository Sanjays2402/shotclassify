"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Key,
  Plus,
  Copy,
  Check,
  Trash,
  Warning,
  Terminal,
  Lock,
  ArrowsClockwise,
} from "@phosphor-icons/react/dist/ssr";

type KeyRow = {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  usage_count: number;
  rotated_at?: string | null;
};

function fmtDate(iso: string | null): string {
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

export default function KeysPage() {
  const [keys, setKeys] = useState<KeyRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [revealed, setRevealed] = useState<{
    name: string;
    plaintext: string;
    rotated?: boolean;
  } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [rotating, setRotating] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/keys", { credentials: "same-origin" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const j = await r.json();
      setKeys(j.keys || []);
      setErr(null);
    } catch (e: any) {
      setErr(e?.message || "Failed to load keys.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onCreate = useCallback(async () => {
    setCreating(true);
    setErr(null);
    try {
      const r = await fetch("/api/keys", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: newName }),
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t || `${r.status} ${r.statusText}`);
      }
      const j = await r.json();
      setRevealed({ name: j.key.name, plaintext: j.plaintext });
      setNewName("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Could not create key.");
    } finally {
      setCreating(false);
    }
  }, [newName, load]);

  const onRotate = useCallback(
    async (id: string, name: string) => {
      if (
        !confirm(
          `Rotate "${name}"? The current secret stops working immediately and a new one is generated. You will see it once.`,
        )
      ) {
        return;
      }
      setRotating(id);
      setErr(null);
      try {
        const r = await fetch(
          `/api/keys/${encodeURIComponent(id)}/rotate`,
          { method: "POST" },
        );
        if (!r.ok) {
          const t = await r.text().catch(() => "");
          throw new Error(t || `${r.status} ${r.statusText}`);
        }
        const j = await r.json();
        setRevealed({
          name: j.key.name,
          plaintext: j.plaintext,
          rotated: true,
        });
        await load();
      } catch (e: any) {
        setErr(e?.message || "Rotate failed.");
      } finally {
        setRotating(null);
      }
    },
    [load],
  );

  const onRevoke = useCallback(
    async (id: string) => {
      if (!confirm("Revoke this key? Calls using it will start failing immediately.")) return;
      setRevoking(id);
      try {
        const r = await fetch(`/api/keys/${encodeURIComponent(id)}`, {
          method: "DELETE",
        });
        if (!r.ok) throw new Error(`${r.status}`);
        await load();
      } catch (e: any) {
        setErr(e?.message || "Revoke failed.");
      } finally {
        setRevoking(null);
      }
    },
    [load],
  );

  const copy = useCallback(async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      setTimeout(() => setCopied((c) => (c === id ? null : c)), 1500);
    } catch {
      /* ignore */
    }
  }, []);

  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:3000";
  const sampleCurl = `curl -X POST ${origin}/v1/classify \\
  -H "Authorization: Bearer ${revealed?.plaintext ?? "sk_live_YOUR_KEY"}" \\
  -F "file=@screenshot.png"`;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow flex items-center gap-1.5">
            <Key size={12} weight="duotone" />
            <span>API access</span>
          </div>
          <h1 className="h-display text-[28px] mt-1 tracking-tight">API keys</h1>
          <p className="text-[13px] mt-1" style={{ color: "var(--color-ink-mute)" }}>
            Generate a key, then call the classifier from your code. Each key tracks its own usage.
          </p>
        </div>
      </header>

      {err && (
        <div
          className="flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]"
          style={{ borderColor: "var(--color-rule)", background: "var(--color-chalk)" }}
        >
          <Warning size={16} weight="duotone" />
          <span>{err}</span>
        </div>
      )}

      {/* Create */}
      <section
        className="rounded-md border p-4 sm:p-5"
        style={{ borderColor: "var(--color-rule)", background: "var(--color-chalk)" }}
      >
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[200px]">
            <label htmlFor="key-name" className="eyebrow block mb-1">
              Name
            </label>
            <input
              id="key-name"
              type="text"
              placeholder="e.g. local dev, ci, production"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              maxLength={80}
              className="w-full rounded-md border px-3 py-2 text-[13px] bg-white outline-none focus:ring-2"
              style={{
                borderColor: "var(--color-rule)",
              }}
            />
          </div>
          <button
            type="button"
            onClick={onCreate}
            disabled={creating}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-[13px] font-medium bg-white hover:bg-[color:var(--color-chalk)] disabled:opacity-50"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <Plus size={14} weight="duotone" />
            {creating ? "Generating..." : "Generate key"}
          </button>
        </div>
      </section>

      {/* Revealed-once banner */}
      {revealed && (
        <section
          className="rounded-md border p-4 sm:p-5 space-y-3"
          style={{
            borderColor: "var(--color-felt)",
            background: "#f6fbf8",
          }}
        >
          <div className="flex items-center gap-2">
            <Lock size={16} weight="duotone" />
            <h2 className="h-display text-[15px]">
              {revealed.rotated ? "Copy your rotated key now" : "Copy your key now"}
            </h2>
          </div>
          <p className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
            This is the only time the full key will be shown. Store it somewhere safe.
          </p>
          <div className="flex items-stretch gap-2">
            <code
              className="flex-1 min-w-0 truncate rounded-md border px-3 py-2 text-[12px] font-mono bg-white"
              style={{ borderColor: "var(--color-rule)" }}
            >
              {revealed.plaintext}
            </code>
            <button
              type="button"
              onClick={() => copy("revealed", revealed.plaintext)}
              className="inline-flex items-center gap-1.5 rounded-md border px-3 text-[13px] bg-white hover:bg-[color:var(--color-chalk)]"
              style={{ borderColor: "var(--color-rule)" }}
              aria-label="Copy key"
            >
              {copied === "revealed" ? (
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
          <details className="text-[12px]" open>
            <summary className="cursor-pointer eyebrow flex items-center gap-1.5">
              <Terminal size={12} weight="duotone" /> Sample request
            </summary>
            <pre
              className="mt-2 overflow-x-auto rounded-md border p-3 text-[12px] font-mono bg-white"
              style={{ borderColor: "var(--color-rule)" }}
            >
{sampleCurl}
            </pre>
          </details>
          <div>
            <button
              type="button"
              onClick={() => setRevealed(null)}
              className="text-[12px] underline"
              style={{ color: "var(--color-ink-mute)" }}
            >
              I have copied it, dismiss
            </button>
          </div>
        </section>
      )}

      {/* List */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="h-display text-[15px]">Your keys</h2>
          {keys && (
            <span className="eyebrow">
              {keys.length} {keys.length === 1 ? "key" : "keys"}
            </span>
          )}
        </div>

        {keys === null ? (
          <div className="space-y-2" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-14 rounded-md border animate-pulse"
                style={{
                  borderColor: "var(--color-rule)",
                  background: "var(--color-chalk)",
                }}
              />
            ))}
          </div>
        ) : keys.length === 0 ? (
          <div
            className="rounded-md border p-6 text-center"
            style={{ borderColor: "var(--color-rule)", background: "var(--color-chalk)" }}
          >
            <Key size={28} weight="duotone" className="mx-auto opacity-60" />
            <p className="mt-2 text-[13px]">No keys yet.</p>
            <p className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
              Generate one above to start calling the API.
            </p>
          </div>
        ) : (
          <div
            className="rounded-md border overflow-hidden"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <table className="w-full text-[13px]">
              <thead
                className="text-left eyebrow"
                style={{ background: "var(--color-chalk)" }}
              >
                <tr>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Prefix</th>
                  <th className="px-3 py-2 hidden sm:table-cell">Created</th>
                  <th className="px-3 py-2 hidden md:table-cell">Last used</th>
                  <th className="px-3 py-2 text-right">Calls</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr
                    key={k.id}
                    className="border-t"
                    style={{ borderColor: "var(--color-rule)" }}
                  >
                    <td className="px-3 py-2 font-medium truncate max-w-[14ch]">
                      {k.name}
                    </td>
                    <td className="px-3 py-2 font-mono text-[12px]">
                      {k.prefix}...
                    </td>
                    <td className="px-3 py-2 hidden sm:table-cell" style={{ color: "var(--color-ink-mute)" }}>
                      {fmtDate(k.created_at)}
                    </td>
                    <td className="px-3 py-2 hidden md:table-cell" style={{ color: "var(--color-ink-mute)" }}>
                      {fmtDate(k.last_used_at)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {k.usage_count}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex items-center gap-1.5 justify-end">
                        <button
                          type="button"
                          onClick={() => onRotate(k.id, k.name)}
                          disabled={rotating === k.id || revoking === k.id}
                          className="inline-flex items-center gap-1 text-[12px] px-2 py-1 rounded-md border bg-white hover:bg-[color:var(--color-chalk)] disabled:opacity-50"
                          style={{ borderColor: "var(--color-rule)" }}
                          aria-label={`Rotate ${k.name}`}
                          title={
                            k.rotated_at
                              ? `Last rotated ${fmtDate(k.rotated_at)}`
                              : "Issue a new secret for this key"
                          }
                        >
                          <ArrowsClockwise size={12} weight="duotone" />
                          {rotating === k.id ? "Rotating" : "Rotate"}
                        </button>
                        <button
                          type="button"
                          onClick={() => onRevoke(k.id)}
                          disabled={revoking === k.id || rotating === k.id}
                          className="inline-flex items-center gap-1 text-[12px] px-2 py-1 rounded-md border bg-white hover:bg-[color:var(--color-chalk)] disabled:opacity-50"
                          style={{ borderColor: "var(--color-rule)" }}
                          aria-label={`Revoke ${k.name}`}
                        >
                          <Trash size={12} weight="duotone" />
                          {revoking === k.id ? "Revoking" : "Revoke"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Always-on usage example */}
      <section
        className="rounded-md border p-4 sm:p-5 space-y-3"
        style={{ borderColor: "var(--color-rule)", background: "var(--color-chalk)" }}
      >
        <div className="flex items-center gap-2">
          <Terminal size={16} weight="duotone" />
          <h2 className="h-display text-[15px]">Using your key</h2>
        </div>
        <p className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
          POST a multipart form with a single <code>file</code> field. The response is the
          classifier JSON, identical to the in-app result.
        </p>
        <pre
          className="overflow-x-auto rounded-md border p-3 text-[12px] font-mono bg-white"
          style={{ borderColor: "var(--color-rule)" }}
        >
{`curl -X POST ${origin}/v1/classify \\
  -H "Authorization: Bearer sk_live_YOUR_KEY" \\
  -F "file=@screenshot.png"`}
        </pre>
      </section>
    </div>
  );
}
