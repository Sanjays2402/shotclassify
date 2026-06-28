// Pure serializers for the /webhooks "Recent deliveries" per-row export
// (F123). The /shots list already lets you grab one row as JSON / Markdown /
// CSV (RowExportMenu, F97); this brings the same affordance to a single
// delivery so a failing webhook attempt -- its event, status, HTTP code, error
// and signed-payload preview -- can be lifted straight into a bug report or a
// support thread without screenshotting the table. Framework-free so the
// formatting is unit-testable without a DOM; the DeliveryExportMenu component
// wraps these with the clipboard API + toast.
//
// CSV is intentionally NOT offered here (unlike the shots row menu): a delivery
// carries a multi-line JSON payload_preview that doesn't belong in a flat
// spreadsheet cell, so JSON + Markdown are the two formats that actually serve
// the "paste into an issue" use case.

// The subset of a delivery row the exporters consume. The page's Delivery type
// is a superset; we only read what's worth exporting so the serializer stays
// decoupled from the wire schema.
export type DeliveryExportInput = {
  id: string;
  event: string;
  url: string;
  status: string;
  attempt: number;
  http_status?: number | null;
  error?: string | null;
  latency_ms?: number | null;
  created_at?: string;
  // The signed JSON body we POSTed, stored as a string preview. Often valid
  // JSON but may be truncated / non-JSON, so the serializers tolerate both.
  payload_preview?: string | null;
};

// Try to parse the payload preview as JSON so the exported object nests the
// real structure rather than a string blob. Returns the parsed value on
// success, or the trimmed raw string when it isn't valid JSON (a truncated
// preview, say). Null / blank previews return undefined so the key is omitted.
export function parsePayloadPreview(
  preview: string | null | undefined,
): unknown {
  if (typeof preview !== "string") return undefined;
  const trimmed = preview.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

// Build a plain, JSON-serialisable object for one delivery. Stable key order,
// omits empty slots so the payload stays tight. The payload preview is parsed
// into real JSON when possible (see parsePayloadPreview).
export function deliveryToExportObject(
  d: DeliveryExportInput,
): Record<string, unknown> {
  const obj: Record<string, unknown> = {
    id: d.id,
    event: d.event,
    url: d.url,
    status: d.status,
    attempt: d.attempt,
  };
  if (typeof d.http_status === "number") obj.http_status = d.http_status;
  if (d.error && d.error.trim()) obj.error = d.error.trim();
  if (typeof d.latency_ms === "number") obj.latency_ms = d.latency_ms;
  if (d.created_at) obj.created_at = d.created_at;
  const payload = parsePayloadPreview(d.payload_preview);
  if (payload !== undefined) obj.payload = payload;
  return obj;
}

// Pretty-printed JSON (2-space indent) for the "copy as JSON" item.
export function deliveryToJson(d: DeliveryExportInput): string {
  return JSON.stringify(deliveryToExportObject(d), null, 2);
}

// Escape pipe + newlines so a value can't break a Markdown table row.
function mdCell(v: string): string {
  return v.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

// Build a Markdown document for one delivery suitable for pasting into an
// issue: a heading, a key/value summary table, and the payload preview as a
// fenced block (pretty-printed when it parses as JSON, raw otherwise). Empty
// sections are omitted.
export function deliveryToMarkdown(d: DeliveryExportInput): string {
  const lines: string[] = [];
  lines.push(`# Delivery ${d.id} — ${mdCell(d.event)}`);
  lines.push("");
  lines.push("| Field | Value |");
  lines.push("| --- | --- |");
  lines.push(`| Status | \`${mdCell(d.status)}\` |`);
  lines.push(`| Event | \`${mdCell(d.event)}\` |`);
  lines.push(`| URL | ${mdCell(d.url)} |`);
  lines.push(`| Attempt | ${d.attempt} |`);
  if (typeof d.http_status === "number")
    lines.push(`| HTTP | ${d.http_status} |`);
  if (typeof d.latency_ms === "number")
    lines.push(`| Latency | ${d.latency_ms} ms |`);
  if (d.created_at) lines.push(`| When | ${mdCell(d.created_at)} |`);
  if (d.error && d.error.trim())
    lines.push(`| Error | ${mdCell(d.error.trim())} |`);

  const payload = parsePayloadPreview(d.payload_preview);
  if (payload !== undefined) {
    lines.push("");
    lines.push("## Payload");
    lines.push("");
    // Pretty-print parsed JSON; a raw string preview prints verbatim.
    const body =
      typeof payload === "string"
        ? payload
        : JSON.stringify(payload, null, 2);
    lines.push("```json");
    lines.push(body);
    lines.push("```");
  }

  lines.push("");
  return lines.join("\n");
}

// --- Export-format catalogue (delivery surface) --------------------------
// Mirrors lib/shot-export's EXPORT_FORMATS so the delivery menu renders its
// items by mapping a catalogue too -- but it lists only the two formats a
// delivery supports (no CSV). Adding a format here lights it up in the menu.
export type DeliveryExportFormatKey = "json" | "markdown";

export type DeliveryExportFormatMeta = {
  key: DeliveryExportFormatKey;
  // Full noun, doubles as the menu label and the toast noun.
  noun: "JSON" | "Markdown";
};

export const DELIVERY_EXPORT_FORMATS: readonly DeliveryExportFormatMeta[] = [
  { key: "json", noun: "JSON" },
  { key: "markdown", noun: "Markdown" },
] as const;

// Serialize a delivery in the requested format. Centralised so the component
// dispatches by key rather than branching inline.
export function serializeDelivery(
  format: DeliveryExportFormatKey,
  d: DeliveryExportInput,
): string {
  return format === "json" ? deliveryToJson(d) : deliveryToMarkdown(d);
}
