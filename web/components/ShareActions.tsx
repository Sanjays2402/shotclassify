"use client";

import { useCallback, useMemo, useState } from "react";
import {
  Link as LinkIcon,
  Check,
  CodeSimple,
} from "@phosphor-icons/react/dist/ssr";

// Copy-link and copy-embed buttons for public share pages and shot
// detail pages. Embed snippet points at /embed/<id>, the chrome-less
// route handler that any third-party site can iframe.
export default function ShareActions({ id }: { id: string }) {
  const [copied, setCopied] = useState<null | "link" | "embed">(null);
  const [err, setErr] = useState<string | null>(null);

  const origin =
    typeof window !== "undefined" ? window.location.origin : "";
  const shareUrl = `${origin}/r/${id}`;
  const embedSnippet = useMemo(
    () =>
      `<iframe src="${origin}/embed/${id}" width="560" height="280" frameborder="0" loading="lazy" style="border:0;max-width:100%" title="ShotClassify result"></iframe>`,
    [origin, id],
  );

  const writeClipboard = useCallback(async (text: string): Promise<void> => {
    if (
      typeof navigator !== "undefined" &&
      navigator.clipboard &&
      window.isSecureContext
    ) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }, []);

  const onCopy = useCallback(
    async (kind: "link" | "embed") => {
      setErr(null);
      const text = kind === "link" ? shareUrl : embedSnippet;
      try {
        await writeClipboard(text);
        setCopied(kind);
        setTimeout(() => setCopied(null), 1800);
      } catch {
        setErr("Copy failed. Select and copy manually.");
      }
    },
    [embedSnippet, shareUrl, writeClipboard],
  );

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <a
        href={`/r/${id}`}
        className="num text-[11px] opacity-60 hover:opacity-100"
        title="Open public share page"
      >
        /r/{id.slice(0, 8)}
      </a>
      <button
        onClick={() => onCopy("link")}
        aria-label="Copy share link"
        className="num text-[11px] inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm border focus:outline-none focus-visible:ring-2"
        style={{
          borderColor: "var(--color-rule)",
          background:
            copied === "link" ? "var(--color-ink)" : "transparent",
          color: copied === "link" ? "var(--color-chalk)" : "inherit",
        }}
      >
        {copied === "link" ? (
          <>
            <Check size={14} weight="duotone" /> Copied
          </>
        ) : (
          <>
            <LinkIcon size={14} weight="duotone" /> Copy share link
          </>
        )}
      </button>
      <button
        onClick={() => onCopy("embed")}
        aria-label="Copy embed snippet"
        title="iframe snippet for Notion, Medium, Discourse, or any HTML site"
        className="num text-[11px] inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm border focus:outline-none focus-visible:ring-2"
        style={{
          borderColor: "var(--color-rule)",
          background:
            copied === "embed" ? "var(--color-ink)" : "transparent",
          color: copied === "embed" ? "var(--color-chalk)" : "inherit",
        }}
      >
        {copied === "embed" ? (
          <>
            <Check size={14} weight="duotone" /> Copied
          </>
        ) : (
          <>
            <CodeSimple size={14} weight="duotone" /> Copy embed
          </>
        )}
      </button>
      {err && (
        <span role="alert" className="text-[11px] opacity-70">
          {err}
        </span>
      )}
    </div>
  );
}
