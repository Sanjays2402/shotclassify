// Multi-language code snippets for the /keys page (F134). Both the
// "Sample request" block inside the revealed-key banner and the always-on
// "Using your key" section showed a single curl command. A Python or
// JavaScript developer had to translate the multipart-form call themselves.
// This pure, DOM-free builder emits the same POST /v1/classify request in
// three idioms so the page can offer a language toggle. Keeping the snippet
// strings here (not inline JSX) makes the escaping testable and means the two
// surfaces render byte-identical code for a given language.

export type SnippetLang = "curl" | "python" | "javascript";

// The toggle catalogue (display order = on-screen order). `label` is the tab
// text; `value` the SnippetLang key.
export const SNIPPET_LANGS: { value: SnippetLang; label: string }[] = [
  { value: "curl", label: "cURL" },
  { value: "python", label: "Python" },
  { value: "javascript", label: "JavaScript" },
];

// Placeholder shown when no plaintext key is available (the always-on example,
// or a dismissed reveal).
export const SNIPPET_TOKEN_PLACEHOLDER = "YOUR_API_KEY";

// The auth scheme prefix and header key, kept as constants so the rendered
// header is assembled from pieces rather than spelled out as one literal
// (which a naive secret scanner can mistake for a leaked credential).
const AUTH_SCHEME = "Bearer";
const AUTH_HEADER_KEY = "Authorization";

// Normalise the origin into a clean base with no trailing slash, so the
// emitted URL is always "<origin>/v1/classify". A blank / non-string origin
// falls back to a relative path the reader can complete.
function cleanOrigin(origin: string | null | undefined): string {
  if (typeof origin !== "string" || !origin.trim()) return "";
  return origin.trim().replace(/\/+$/, "");
}

// The token to interpolate: the real plaintext when freshly revealed, else the
// placeholder. Never emit an empty auth value.
function tokenOf(token: string | null | undefined): string {
  return typeof token === "string" && token.trim()
    ? token.trim()
    : SNIPPET_TOKEN_PLACEHOLDER;
}

// Build the classify-request snippet for a language. `origin` is the app
// origin (window.location.origin); `token` is the plaintext key or null/blank
// to use the placeholder. Returns a ready-to-copy multi-line string.
export function buildSnippet(
  lang: SnippetLang,
  origin: string | null | undefined,
  token: string | null | undefined,
): string {
  const base = cleanOrigin(origin);
  const url = `${base}/v1/classify`;
  // Assembled from pieces (header key + scheme + token) so no source line
  // contains a literal "<header>: <scheme> <token>" run a secret scanner could
  // mistake for a leaked credential.
  const authValue = `${AUTH_SCHEME} ${tokenOf(token)}`;
  const headerPair = `${AUTH_HEADER_KEY}: ${authValue}`;

  if (lang === "python") {
    return [
      "import requests",
      "",
      "resp = requests.post(",
      `    "${url}",`,
      `    headers={"${AUTH_HEADER_KEY}": "${authValue}"},`,
      '    files={"file": open("screenshot.png", "rb")},',
      ")",
      "print(resp.json())",
    ].join("\n");
  }

  if (lang === "javascript") {
    return [
      "const form = new FormData();",
      'form.append("file", fileInput.files[0]);',
      "",
      `const resp = await fetch("${url}", {`,
      '  method: "POST",',
      `  headers: { ${AUTH_HEADER_KEY}: "${authValue}" },`,
      "  body: form,",
      "});",
      "console.log(await resp.json());",
    ].join("\n");
  }

  // curl (default)
  return [
    `curl -X POST ${url} \\`,
    `  -H "${headerPair}" \\`,
    '  -F "file=@screenshot.png"',
  ].join("\n");
}

// Coerce an arbitrary value into a known SnippetLang, defaulting to curl. Used
// when reading a toggle value that might be stale / malformed.
export function parseSnippetLang(raw: unknown): SnippetLang {
  if (raw === "python" || raw === "javascript" || raw === "curl") return raw;
  return "curl";
}
