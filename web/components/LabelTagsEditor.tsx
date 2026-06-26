"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { PencilSimple, Plus, Tag, X, Check, Spinner } from "@phosphor-icons/react/dist/ssr";

type Props = {
  id: string;
  label: string | null;
  tags: string[];
  filenameFallback: string;
  disabled?: boolean;
  /** Rendered inside a CollapsibleSection (F77): drop the panel chrome since
   * the section already provides the card + header. */
  embedded?: boolean;
};

function normalize(t: string): string {
  return t.trim().toLowerCase().slice(0, 32);
}

export default function LabelTagsEditor({
  id,
  label,
  tags,
  filenameFallback,
  disabled,
  embedded,
}: Props) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [draftLabel, setDraftLabel] = useState(label ?? "");
  const [draftTags, setDraftTags] = useState<string[]>(tags);
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setDraftLabel(label ?? "");
    setDraftTags(tags);
  }, [label, tags, id]);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const dirty = useMemo(() => {
    const a = (draftLabel ?? "").trim();
    const b = (label ?? "").trim();
    if (a !== b) return true;
    if (draftTags.length !== tags.length) return true;
    for (let i = 0; i < draftTags.length; i++) {
      if (draftTags[i] !== tags[i]) return true;
    }
    return false;
  }, [draftLabel, draftTags, label, tags]);

  function addTag(raw: string) {
    const t = normalize(raw);
    if (!t) return;
    if (draftTags.includes(t)) return;
    if (draftTags.length >= 16) return;
    setDraftTags([...draftTags, t]);
    setTagInput("");
  }

  function removeTag(t: string) {
    setDraftTags(draftTags.filter((x) => x !== t));
  }

  function cancel() {
    setDraftLabel(label ?? "");
    setDraftTags(tags);
    setTagInput("");
    setError(null);
    setEditing(false);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const trimmed = draftLabel.trim();
      const body: Record<string, unknown> = {
        label: trimmed ? trimmed : null,
        tags: draftTags,
      };
      const res = await fetch(`/api/shots/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(
          `Save failed (${res.status})${txt ? `: ${txt.slice(0, 160)}` : ""}`
        );
      }
      setEditing(false);
      router.refresh();
    } catch (e: any) {
      setError(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const displayLabel = (label ?? "").trim() || filenameFallback;
  // When embedded in a CollapsibleSection (F77) the section supplies the card,
  // so drop the panel chrome and just stack the contents.
  const wrapClass = embedded ? "flex flex-col gap-3" : "panel p-4 flex flex-col gap-3";

  if (!editing) {
    return (
      <div className={wrapClass}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="eyebrow mb-1">Label</div>
            <div
              className="text-[15px] font-medium truncate max-w-[52ch]"
              title={displayLabel}
            >
              {displayLabel}
              {!label && (
                <span className="ml-2 num text-[10px] opacity-50 uppercase">
                  from filename
                </span>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setEditing(true)}
            disabled={disabled}
            className="btn btn-ghost text-[12px] inline-flex items-center gap-1.5 shrink-0 disabled:opacity-40"
            aria-label="Edit label and tags"
          >
            <PencilSimple size={14} weight="duotone" />
            Edit
          </button>
        </div>
        <div>
          <div className="eyebrow mb-1.5">Tags</div>
          {tags.length === 0 ? (
            <div className="text-[12px] opacity-50">
              No tags yet. Add a few to filter this shot from the history page.
            </div>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {tags.map((t) => (
                <li
                  key={t}
                  className="num text-[11px] inline-flex items-center gap-1 px-2 py-[3px] rounded-sm border border-black/20 bg-black/[0.03]"
                >
                  <Tag size={11} weight="duotone" />
                  {t}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={wrapClass}>
      <div>
        <label className="eyebrow mb-1 block" htmlFor={`label-${id}`}>
          Label
        </label>
        <input
          ref={inputRef}
          id={`label-${id}`}
          type="text"
          value={draftLabel}
          maxLength={256}
          placeholder={filenameFallback}
          onChange={(e) => setDraftLabel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void save();
            } else if (e.key === "Escape") {
              cancel();
            }
          }}
          className="w-full text-[14px] px-2 py-1.5 border border-black/30 rounded-sm bg-white focus:outline-none focus:border-black"
        />
      </div>
      <div>
        <div className="eyebrow mb-1.5">Tags ({draftTags.length}/16)</div>
        <ul className="flex flex-wrap gap-1.5 mb-2">
          {draftTags.map((t) => (
            <li
              key={t}
              className="num text-[11px] inline-flex items-center gap-1 px-2 py-[3px] rounded-sm border border-black/20 bg-black/[0.03]"
            >
              <Tag size={11} weight="duotone" />
              {t}
              <button
                type="button"
                onClick={() => removeTag(t)}
                aria-label={`Remove tag ${t}`}
                className="ml-0.5 opacity-60 hover:opacity-100"
              >
                <X size={11} weight="bold" />
              </button>
            </li>
          ))}
        </ul>
        <div className="flex gap-1.5">
          <input
            type="text"
            value={tagInput}
            maxLength={32}
            placeholder="Add a tag and press Enter"
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                addTag(tagInput);
              } else if (e.key === "Backspace" && !tagInput && draftTags.length) {
                setDraftTags(draftTags.slice(0, -1));
              }
            }}
            className="flex-1 text-[12px] px-2 py-1 border border-black/30 rounded-sm bg-white focus:outline-none focus:border-black"
          />
          <button
            type="button"
            onClick={() => addTag(tagInput)}
            disabled={!normalize(tagInput) || draftTags.length >= 16}
            className="btn btn-ghost text-[11px] inline-flex items-center gap-1 disabled:opacity-40"
          >
            <Plus size={12} weight="bold" />
            Add
          </button>
        </div>
      </div>
      {error && (
        <div className="text-[11px] text-red-700" role="alert">
          {error}
        </div>
      )}
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={cancel}
          disabled={saving}
          className="btn btn-ghost text-[12px]"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={save}
          disabled={saving || !dirty}
          className="btn btn-primary text-[12px] inline-flex items-center gap-1.5 disabled:opacity-40"
        >
          {saving ? (
            <Spinner size={12} weight="bold" className="animate-spin" />
          ) : (
            <Check size={12} weight="bold" />
          )}
          Save
        </button>
      </div>
    </div>
  );
}
