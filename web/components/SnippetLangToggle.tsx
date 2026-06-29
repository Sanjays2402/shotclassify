"use client";

// Shared segmented control choosing the API snippet language (curl / Python /
// JavaScript) — extracted from the /keys page (F134) so the /keys/[id] detail
// page reuses it (F141) and the two surfaces can never drift visually. Purely
// presentational: selection state + persistence live in the page. Drives the
// shared buildSnippet (lib/key-snippet), so a single choice feeds every block.

import { SNIPPET_LANGS, type SnippetLang } from "@/lib/key-snippet";

export function SnippetLangToggle({
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

export default SnippetLangToggle;
