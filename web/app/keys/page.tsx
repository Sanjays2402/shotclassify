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
import {
  SCOPE_OPTIONS,
  scopesForSelection,
  scopeLabel,
  scopeDescription,
  scopeCanWrite,
  type KeyScope,
  type ScopeTier,
} from "@/lib/key-scope";
import {
  keyRelativeLabel,
  keyUsageStatus,
  keyStatusLabel,
  keyStatusHint,
} from "@/lib/key-activity";
import { validateKeyName } from "@/lib/key-name";
import { summarizeKeys, keysSummaryChips } from "@/lib/key-summary";
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
import {
  isArmed,
  confirmLabel,
  confirmPrompt,
  nextOnTrigger,
  type KeyConfirmPending,
} from "@/lib/key-confirm";
import {
  distinctWorkspaces,
  hasMultipleWorkspaces,
  filterByWorkspace,
  workspaceChipLabel,
  DEFAULT_WORKSPACE,
} from "@/lib/key-workspace";

type KeyRow = {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  usage_count: number;
  rotated_at?: string | null;
  scopes?: KeyScope[];
  workspace_id?: string;
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

// A compact segmented control choosing the snippet language (F134). Shared by
// the revealed-key sample and the always-on example so a single selection
// drives both blocks. Purely presentational -- state lives in the page.
function LangToggle({
  value,
  onChange,
}: {
  value: SnippetLang;
  onChange: (lang: SnippetLang) => void;
}) {
  return (
    <div
      className="inline-flex items-center rounded-md border overflow-hidden"
      style={{ borderColor: "var(--color-rule)" }}
      role="group"
      aria-label="Snippet language"
    >
      {SNIPPET_LANGS.map((l) => {
        const active = value === l.value;
        return (
          <button
            key={l.value}
            type="button"
            onClick={() => onChange(l.value)}
            aria-pressed={active}
            className="text-[11px] px-2 py-1 font-mono"
            style={{
              background: active ? "var(--color-felt)" : "transparent",
              color: active ? "var(--color-chalk)" : "var(--color-ink-mute)",
            }}
          >
            {l.label}
          </button>
        );
      })}
    </div>
  );
}

export default function KeysPage() {
  const [keys, setKeys] = useState<KeyRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newWorkspace, setNewWorkspace] = useState("");
  const [newScope, setNewScope] = useState<ScopeTier>("write");
  const [revealed, setRevealed] = useState<{
    name: string;
    plaintext: string;
    rotated?: boolean;
  } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [rotating, setRotating] = useState<string | null>(null);
  // Inline two-step destructive confirmation (F136) replaces browser confirm().
  // One row at a time can be armed; the second click on the same Confirm fires.
  const [pendingConfirm, setPendingConfirm] = useState<KeyConfirmPending>(null);
  // Workspace filter (F137): multi-tenant installs interleave keys from many
  // workspaces; this narrows the list to one. null = all. Chip-driven.
  const [wsFilter, setWsFilter] = useState<string | null>(null);
  // Which language the code snippets render in (F134). One toggle drives both
  // the revealed-key "Sample request" block and the always-on "Using your key"
  // section so they never disagree. Persisted across visits (F135) -- a Python
  // shop reopens on Python -- via a mount read + a setter that writes through.
  const [snippetLang, setSnippetLang] = useState<SnippetLang>(
    KEY_SNIPPET_LANG_DEFAULT,
  );
  const chooseSnippetLang = useCallback((lang: SnippetLang) => {
    setSnippetLang(lang);
    writeSnippetLang(lang);
  }, []);
  // Resolve the stored language after mount (SSR renders the default so the
  // first client paint matches, then this fills the saved choice).
  useEffect(() => {
    setSnippetLang(readSnippetLang());
  }, []);
  // Captured on mount so the relative "last used" labels (F131) render the
  // same value on first client paint as on every subsequent render -- SSR
  // emits 0 (no relative line), the mount effect fills the real clock, and a
  // 60s tick keeps the labels fresh while the page stays open.
  const [now, setNow] = useState(0);
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

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

  // Inline name validation (F132). Existing names drive the duplicate check;
  // `nameTouched` keeps a pristine empty field from showing a red error before
  // the user has typed anything, while still gating the Generate button.
  const [nameTouched, setNameTouched] = useState(false);
  const existingNames = (keys ?? []).map((k) => k.name);
  const nameValidation = validateKeyName(newName, existingNames);
  const showNameError = nameTouched && !nameValidation.ok && newName.length > 0;

  const onCreate = useCallback(async () => {
    setCreating(true);
    setErr(null);
    try {
      const r = await fetch("/api/keys", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: nameValidation.normalized || newName,
          workspace_id: newWorkspace.trim() || undefined,
          scopes: scopesForSelection(newScope),
        }),
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t || `${r.status} ${r.statusText}`);
      }
      const j = await r.json();
      setRevealed({ name: j.key.name, plaintext: j.plaintext });
      setNewName("");
      setNewWorkspace("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Could not create key.");
    } finally {
      setCreating(false);
    }
  }, [newName, newWorkspace, newScope, load]);

  const onRotate = useCallback(
    async (id: string) => {
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

  // F136: drive the destructive buttons through the two-step state machine.
  // First click on a key's Rotate/Revoke arms it (inline prompt appears);
  // the Confirm click fires the real mutation. Cancel clears the armed state.
  const triggerConfirm = useCallback(
    (action: "rotate" | "revoke", id: string) => {
      setPendingConfirm((prev) => {
        const { fire, pending } = nextOnTrigger(prev, action, id);
        if (fire) {
          if (action === "rotate") onRotate(id);
          else onRevoke(id);
        }
        return pending;
      });
    },
    [onRotate, onRevoke],
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
  // The revealed-key sample uses the real plaintext; the always-on example
  // uses the placeholder. Both go through buildSnippet (F134) for the selected
  // language so curl / Python / JavaScript stay in lockstep.
  const sampleSnippet = buildSnippet(snippetLang, origin, revealed?.plaintext ?? null);
  const exampleSnippet = buildSnippet(snippetLang, origin, null);

  // Workspace grouping (F137): on a multi-tenant install, show a chip row to
  // narrow the table to one workspace; visible keys feed the table while the
  // summary chips above keep counting the whole fleet.
  const allKeys = keys ?? [];
  const showWorkspaceFilter = hasMultipleWorkspaces(allKeys);
  const workspaceCounts = distinctWorkspaces(allKeys);
  const visibleKeys = filterByWorkspace(allKeys, wsFilter);

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
              onBlur={() => setNameTouched(true)}
              maxLength={80}
              aria-invalid={showNameError}
              aria-describedby={showNameError ? "key-name-error" : undefined}
              className="w-full rounded-md border px-3 py-2 text-[13px] bg-white outline-none focus:ring-2"
              style={{
                borderColor: showNameError
                  ? "var(--color-conf-low)"
                  : "var(--color-rule)",
              }}
            />
            {showNameError && (
              <p
                id="key-name-error"
                className="mt-1 text-[11px] flex items-center gap-1"
                style={{ color: "var(--color-conf-low)" }}
              >
                <Warning size={11} weight="duotone" />
                {nameValidation.message}
              </p>
            )}
          </div>
          <div className="min-w-[180px]">
            <label htmlFor="key-workspace" className="eyebrow block mb-1">
              Workspace
            </label>
            <input
              id="key-workspace"
              type="text"
              placeholder="default"
              value={newWorkspace}
              onChange={(e) => setNewWorkspace(e.target.value)}
              maxLength={64}
              pattern="[A-Za-z0-9][A-Za-z0-9_\-]*"
              aria-describedby="key-workspace-help"
              className="w-full rounded-md border px-3 py-2 text-[13px] bg-white outline-none focus:ring-2 font-mono"
              style={{ borderColor: "var(--color-rule)" }}
            />
            <p
              id="key-workspace-help"
              className="mt-1 text-[11px]"
              style={{ color: "var(--color-ink-mute)" }}
            >
              Webhooks and deliveries are isolated per workspace.
            </p>
          </div>
          <div className="min-w-[180px]">
            <label htmlFor="key-scope" className="eyebrow block mb-1">
              Scope
            </label>
            <select
              id="key-scope"
              value={newScope}
              onChange={(e) => setNewScope(e.target.value as ScopeTier)}
              className="w-full rounded-md border px-3 py-2 text-[13px] bg-white outline-none focus:ring-2"
              style={{ borderColor: "var(--color-rule)" }}
              aria-describedby="key-scope-help"
            >
              {SCOPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <p
              id="key-scope-help"
              className="mt-1 text-[11px]"
              style={{ color: "var(--color-ink-mute)" }}
            >
              {scopeDescription(scopesForSelection(newScope))}
            </p>
          </div>
          <button
            type="button"
            onClick={onCreate}
            disabled={creating || !nameValidation.ok}
            title={
              !nameValidation.ok && newName.length > 0
                ? nameValidation.message
                : !nameValidation.ok
                  ? "Name the key first"
                  : "Generate a new API key"
            }
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-[13px] font-medium bg-white hover:bg-[color:var(--color-chalk)] disabled:opacity-50 disabled:cursor-not-allowed"
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
            <div className="mt-2 flex items-center justify-between gap-2">
              <LangToggle value={snippetLang} onChange={chooseSnippetLang} />
              <button
                type="button"
                onClick={() => copy("sample", sampleSnippet)}
                className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border bg-white hover:bg-[color:var(--color-chalk)]"
                style={{ borderColor: "var(--color-rule)" }}
                aria-label="Copy sample request"
              >
                {copied === "sample" ? (
                  <>
                    <Check size={12} weight="duotone" /> Copied
                  </>
                ) : (
                  <>
                    <Copy size={12} weight="duotone" /> Copy
                  </>
                )}
              </button>
            </div>
            <pre
              className="mt-2 overflow-x-auto rounded-md border p-3 text-[12px] font-mono bg-white"
              style={{ borderColor: "var(--color-rule)" }}
            >
{sampleSnippet}
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
        <div className="flex items-center justify-between gap-3">
          <h2 className="h-display text-[15px]">Your keys</h2>
          {keys && keys.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 justify-end">
              {keysSummaryChips(summarizeKeys(keys, now)).map((c) => (
                <span
                  key={c.key}
                  className="inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-mono"
                  title={c.hint}
                  style={{
                    borderColor: "var(--color-rule)",
                    background: "var(--color-chalk)",
                    color:
                      c.tone === "warn"
                        ? "var(--color-cue-deep, #9a7a0a)"
                        : c.tone === "mute"
                          ? "var(--color-conf-low)"
                          : "var(--color-ink)",
                  }}
                >
                  {c.label}
                </span>
              ))}
            </div>
          )}
        </div>

        {showWorkspaceFilter && (
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by workspace">
            <button
              type="button"
              onClick={() => setWsFilter(null)}
              aria-pressed={wsFilter === null}
              className="inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-mono"
              style={{
                borderColor: "var(--color-rule)",
                background: wsFilter === null ? "var(--color-felt)" : "var(--color-chalk)",
                color: wsFilter === null ? "var(--color-chalk)" : "var(--color-ink-mute)",
              }}
            >
              All ({allKeys.length})
            </button>
            {workspaceCounts.map((w) => {
              const active = wsFilter === w.workspace;
              return (
                <button
                  key={w.workspace}
                  type="button"
                  onClick={() => setWsFilter(active ? null : w.workspace)}
                  aria-pressed={active}
                  className="inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-mono"
                  style={{
                    borderColor: "var(--color-rule)",
                    background: active ? "var(--color-felt)" : "var(--color-chalk)",
                    color: active ? "var(--color-chalk)" : "var(--color-ink-mute)",
                  }}
                  title={
                    w.workspace === DEFAULT_WORKSPACE
                      ? "Keys not bound to a named workspace"
                      : `Show only ${workspaceChipLabel(w.workspace)}`
                  }
                >
                  {workspaceChipLabel(w.workspace)} ({w.count})
                </button>
              );
            })}
          </div>
        )}

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
                  <th className="px-3 py-2">Scope</th>
                  <th className="px-3 py-2 hidden sm:table-cell">Created</th>
                  <th className="px-3 py-2 hidden md:table-cell">Last used</th>
                  <th className="px-3 py-2 text-right">Calls</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {visibleKeys.map((k) => (
                  <tr
                    key={k.id}
                    className="border-t"
                    style={{ borderColor: "var(--color-rule)" }}
                  >
                    <td className="px-3 py-2 font-medium truncate max-w-[14ch]">
                      <a
                        href={`/keys/${encodeURIComponent(k.id)}`}
                        className="hover:underline"
                      >
                        {k.name}
                      </a>
                      {k.workspace_id && k.workspace_id !== "default" ? (
                        <div
                          className="mt-0.5 text-[11px] font-mono"
                          style={{ color: "var(--color-ink-mute)" }}
                          title="Workspace this key is bound to. Webhooks and deliveries are isolated per workspace."
                        >
                          ws: {k.workspace_id}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 font-mono text-[12px]">
                      {k.prefix}...
                    </td>
                    <td className="px-3 py-2">
                      {(() => {
                        const canWrite = scopeCanWrite(k.scopes);
                        return (
                          <span
                            className="inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-mono"
                            style={{
                              borderColor: "var(--color-rule)",
                              background: canWrite
                                ? "#f6fbf8"
                                : "var(--color-chalk)",
                              color: canWrite
                                ? "var(--color-felt, #1a7a4a)"
                                : "var(--color-ink-mute)",
                            }}
                            title={scopeDescription(k.scopes)}
                          >
                            {scopeLabel(k.scopes)}
                          </span>
                        );
                      })()}
                    </td>
                    <td className="px-3 py-2 hidden sm:table-cell" style={{ color: "var(--color-ink-mute)" }}>
                      {fmtDate(k.created_at)}
                    </td>
                    <td className="px-3 py-2 hidden md:table-cell" style={{ color: "var(--color-ink-mute)" }}>
                      {(() => {
                        const status = keyUsageStatus(k, now);
                        const rel = now > 0 ? keyRelativeLabel(k.last_used_at, now) : "";
                        const pill = keyStatusLabel(status);
                        return (
                          <div className="flex flex-col gap-0.5">
                            <span title={k.last_used_at ? fmtDate(k.last_used_at) : "Never used"}>
                              {fmtDate(k.last_used_at)}
                            </span>
                            {rel && (
                              <span className="text-[11px] opacity-70 tabular-nums">{rel}</span>
                            )}
                            {pill && (
                              <span
                                className="inline-flex w-fit items-center rounded-md border px-1.5 py-0.5 text-[10px] font-mono"
                                style={{
                                  borderColor: "var(--color-rule)",
                                  background: "var(--color-chalk)",
                                  color:
                                    status === "unused"
                                      ? "var(--color-conf-low)"
                                      : "var(--color-cue-deep, #9a7a0a)",
                                }}
                                title={keyStatusHint(status)}
                              >
                                {pill}
                              </span>
                            )}
                          </div>
                        );
                      })()}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {k.usage_count}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {(() => {
                        const rotateArmed = isArmed(pendingConfirm, "rotate", k.id);
                        const revokeArmed = isArmed(pendingConfirm, "revoke", k.id);
                        const armedAction = rotateArmed
                          ? "rotate"
                          : revokeArmed
                            ? "revoke"
                            : null;
                        if (armedAction) {
                          // Inline two-step confirm: prompt + Confirm/Cancel.
                          return (
                            <div className="inline-flex items-center gap-2 justify-end">
                              <span
                                className="text-[11px]"
                                style={{ color: "var(--color-ink-mute)" }}
                              >
                                {confirmPrompt(armedAction)}
                              </span>
                              <button
                                type="button"
                                onClick={() => triggerConfirm(armedAction, k.id)}
                                disabled={rotating === k.id || revoking === k.id}
                                className="inline-flex items-center gap-1 text-[12px] px-2 py-1 rounded-md text-white disabled:opacity-50"
                                style={{ background: "var(--color-conf-low)" }}
                                aria-label={`Confirm ${armedAction} ${k.name}`}
                              >
                                {armedAction === "rotate" ? (
                                  <ArrowsClockwise size={12} weight="duotone" />
                                ) : (
                                  <Trash size={12} weight="duotone" />
                                )}
                                {confirmLabel(armedAction, true)}
                              </button>
                              <button
                                type="button"
                                onClick={() => setPendingConfirm(null)}
                                className="text-[12px] px-2 py-1 rounded-md border bg-white hover:bg-[color:var(--color-chalk)]"
                                style={{ borderColor: "var(--color-rule)" }}
                                aria-label="Cancel"
                              >
                                Cancel
                              </button>
                            </div>
                          );
                        }
                        return (
                          <div className="inline-flex items-center gap-1.5 justify-end">
                            <button
                              type="button"
                              onClick={() => triggerConfirm("rotate", k.id)}
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
                              onClick={() => triggerConfirm("revoke", k.id)}
                              disabled={revoking === k.id || rotating === k.id}
                              className="inline-flex items-center gap-1 text-[12px] px-2 py-1 rounded-md border bg-white hover:bg-[color:var(--color-chalk)] disabled:opacity-50"
                              style={{ borderColor: "var(--color-rule)" }}
                              aria-label={`Revoke ${k.name}`}
                            >
                              <Trash size={12} weight="duotone" />
                              {revoking === k.id ? "Revoking" : "Revoke"}
                            </button>
                          </div>
                        );
                      })()}
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
        <div className="flex items-center justify-between gap-2">
          <p className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
            POST a multipart form with a single <code>file</code> field. The response is the
            classifier JSON, identical to the in-app result.
          </p>
          <LangToggle value={snippetLang} onChange={chooseSnippetLang} />
        </div>
        <pre
          className="overflow-x-auto rounded-md border p-3 text-[12px] font-mono bg-white"
          style={{ borderColor: "var(--color-rule)" }}
        >
{exampleSnippet}
        </pre>
      </section>
    </div>
  );
}
