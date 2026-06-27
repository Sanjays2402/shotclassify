"use client";

// Presentational drawer that expands UNDER a /shots row to give a quick look at
// a shot without leaving the list (F84). The connected ShotPreviewRow wrapper
// below owns the lazy detail fetch (it only mounts -- and so only fetches --
// while the row is expanded); the presentational ShotPreviewDrawer just renders
// whatever stage the fetch is in. Display values come entirely from the pure
// lib/shot-preview view-model so the trimming / sorting / fallback logic stays
// testable and these stay thin renderers.

import useSWR from "swr";
import { fetcher, ENDPOINTS } from "@/lib/api";
import { confColor, LONG, type Category } from "@/lib/categories";
import {
  buildShotPreview,
  previewHasContent,
  type ShotPreviewRecord,
} from "@/lib/shot-preview";

export type ShotPreviewDrawerProps = {
  // The shot id (for the "open full" link + accessible labelling).
  id: string;
  // The fetched detail record, or null while loading / on error.
  record: ShotPreviewRecord | null;
  loading: boolean;
  error: boolean;
  // How many table columns the drawer cell must span so it fills the row width.
  colSpan: number;
};

function PreviewBar({ category, pct }: { category: string; pct: number }) {
  const label = LONG[category as Category] ?? category;
  // Reconstruct a 0..1 score for the shared colour ramp from the clamped pct.
  const color = confColor(pct / 100);
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] opacity-80 w-[88px] shrink-0 truncate" title={label}>
        {label}
      </span>
      <div className="conf-bar flex-1" aria-hidden>
        <span style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="num text-[11px] opacity-70 w-[44px] text-right shrink-0">
        {pct.toFixed(1)}%
      </span>
    </div>
  );
}

export function ShotPreviewDrawer({
  id,
  record,
  loading,
  error,
  colSpan,
}: ShotPreviewDrawerProps) {
  const model = record ? buildShotPreview(record) : null;

  return (
    <tr data-preview-row>
      <td colSpan={colSpan} className="p-0">
        <div
          className="px-4 py-3 border-t"
          style={{
            borderColor: "var(--color-rule)",
            background: "color-mix(in srgb, var(--color-felt) 4%, transparent)",
          }}
          role="region"
          aria-label={`Preview of shot ${id}`}
        >
          {loading && (
            <div className="text-[12px] opacity-60 py-1" role="status">
              Loading preview…
            </div>
          )}

          {!loading && error && (
            <div className="text-[12px] py-1" style={{ color: "#b00020" }}>
              Couldn&apos;t load this shot&apos;s details.
            </div>
          )}

          {!loading && !error && model && (
            <>
              {!previewHasContent(model) ? (
                <div className="text-[12px] opacity-60 py-1">
                  Nothing captured for this shot yet.
                </div>
              ) : (
                <div className="grid gap-3 md:grid-cols-2">
                  {/* Left: OCR snippet + rationale. */}
                  <div className="grid gap-3 content-start">
                    {model.ocrSnippet && (
                      <div>
                        <div className="eyebrow mb-1">OCR transcript</div>
                        <p className="num text-[12px] leading-relaxed opacity-85 whitespace-pre-wrap break-words">
                          {model.ocrSnippet}
                          {model.ocrTruncated && (
                            <span className="opacity-50"> (truncated)</span>
                          )}
                        </p>
                      </div>
                    )}
                    {model.rationale && (
                      <div>
                        <div className="eyebrow mb-1">Rationale</div>
                        <p className="text-[12px] leading-relaxed opacity-85 break-words">
                          {model.rationale}
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Right: mini confidence distribution. */}
                  {model.topConfidences.length > 0 && (
                    <div>
                      <div className="eyebrow mb-1.5">Confidence</div>
                      <div className="grid gap-1.5">
                        {model.topConfidences.map((c) => (
                          <PreviewBar
                            key={c.category}
                            category={c.category}
                            pct={c.pct}
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="mt-2.5">
                <a
                  href={`/shots/${id}`}
                  className="text-[11px] underline opacity-70 hover:opacity-100"
                >
                  Open full shot →
                </a>
              </div>
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

export default ShotPreviewDrawer;

// Connected wrapper rendered by the /shots table for an expanded row. Because
// it only mounts while the row is open, the SWR fetch is naturally lazy -- no
// detail request fires until the user expands a row, and SWR caches it so
// re-expanding the same row is instant. Reuses the same /api/shots/[id]
// endpoint + fetcher the detail page uses, so an already-visited shot is served
// from cache. Keeps the page a thin caller: it just renders <ShotPreviewRow>
// for each id in its `expanded` set.
export function ShotPreviewRow({
  id,
  colSpan,
}: {
  id: string;
  colSpan: number;
}) {
  const { data, error, isLoading } = useSWR<ShotPreviewRecord>(
    ENDPOINTS.historyItem(id),
    fetcher,
  );
  return (
    <ShotPreviewDrawer
      id={id}
      record={data ?? null}
      loading={isLoading && !data}
      error={!!error && !data}
      colSpan={colSpan}
    />
  );
}
