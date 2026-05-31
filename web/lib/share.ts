// Server-side fetch helper for public share pages.
// Calls the FastAPI service directly using the server-only API key.
// Never expose this module to the client.
import "server-only";

const API = process.env.SHOTCLASSIFY_API_BASE || "http://127.0.0.1:7441";
const KEY = process.env.SHOTCLASSIFY_API_KEY || "";

export type ShareRecord = {
  id: string;
  filename: string;
  created_at: string;
  primary_category: string;
  confidence: number;
  elapsed_ms?: number;
  source?: string;
  ocr_text?: string;
  user_corrected_to?: string | null;
  classification?: {
    primary: string;
    confidences: { category: string; score: number }[];
    rationale?: string;
  };
  ocr?: { text?: string; word_count?: number; mean_confidence?: number };
};

export async function fetchShareRecord(id: string): Promise<ShareRecord | null> {
  try {
    const res = await fetch(`${API}/v1/history/${encodeURIComponent(id)}`, {
      headers: KEY ? { "x-api-key": KEY } : {},
      // Public share pages are cacheable for 5 minutes.
      next: { revalidate: 300 },
    });
    if (!res.ok) return null;
    return (await res.json()) as ShareRecord;
  } catch {
    return null;
  }
}
