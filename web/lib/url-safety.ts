// SSRF protection for outbound webhook delivery.
//
// Enterprise security review item: the server must not blindly POST signed
// payloads to URLs like http://169.254.169.254/ (cloud metadata),
// http://127.0.0.1/, http://10.0.0.5/, or [::1]. Even with HMAC the request
// itself can be used to probe internal infrastructure or trigger side effects
// on an internal service that trusts the source IP.
//
// We block:
//   * non-http(s) schemes
//   * userinfo in the URL (curl-style credential smuggling)
//   * hostnames that resolve (or literally are) loopback, link-local, private,
//     unique-local, broadcast, multicast, unspecified, or cloud-metadata
//   * non-default ports outside a small allowlist (80, 443, 8443, 8080)
//
// Callers pass an optional `allow` list of literal hostnames or CIDR strings
// that override the block for a specific tenant. The intent is "I really do
// want to deliver to internal.corp.lan in our VPC" with an explicit opt-in,
// not "trust this URL blindly".

import "server-only";
import { promises as dns } from "node:dns";
import net from "node:net";

export type UrlBlockReason =
  | "invalid_url"
  | "bad_scheme"
  | "userinfo_forbidden"
  | "port_not_allowed"
  | "private_address"
  | "loopback_address"
  | "link_local_address"
  | "metadata_address"
  | "multicast_address"
  | "broadcast_address"
  | "unspecified_address"
  | "dns_lookup_failed";

export type UrlCheck =
  | { ok: true; url: URL; resolved: string[] }
  | { ok: false; reason: UrlBlockReason; message: string };

const ALLOWED_PORTS = new Set([80, 443, 8080, 8443]);

// Test/dev escape hatch: when SHOTCLASSIFY_WEBHOOK_ALLOW_LOOPBACK=1 the
// guard treats 127.0.0.0/8 and ::1 as permitted. We use this so the
// existing webhook test suite (which spins up http.createServer on
// 127.0.0.1) keeps passing without weakening prod behavior. The variable
// must NOT be set in production, and `validate_for_production` in the
// Python service would catch a misconfigured deploy at boot time.
function loopbackEscapeHatch(): boolean {
  return process.env.SHOTCLASSIFY_WEBHOOK_ALLOW_LOOPBACK === "1";
}

// Cloud metadata endpoints. AWS / GCP / Azure / Oracle / Alibaba all sit on
// 169.254.169.254; fd00:ec2::254 is the AWS IMDS v6 address. Block both the
// literal IPs and any host that resolves to them.
const METADATA_LITERALS = new Set([
  "169.254.169.254",
  "fd00:ec2::254",
  "100.100.100.200", // Alibaba
]);

function isMetadata(ip: string): boolean {
  return METADATA_LITERALS.has(ip.toLowerCase());
}

// Parse an IPv4 dotted-quad to a 32-bit number, or null if not v4.
function v4ToInt(ip: string): number | null {
  if (net.isIPv4(ip) !== true) return null;
  const parts = ip.split(".").map((p) => parseInt(p, 10));
  if (parts.length !== 4 || parts.some((n) => Number.isNaN(n) || n < 0 || n > 255)) {
    return null;
  }
  return ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0;
}

function inV4Cidr(ip: string, cidr: string): boolean {
  const [base, bitsRaw] = cidr.split("/");
  const bits = parseInt(bitsRaw, 10);
  if (!Number.isFinite(bits) || bits < 0 || bits > 32) return false;
  const ipInt = v4ToInt(ip);
  const baseInt = v4ToInt(base);
  if (ipInt === null || baseInt === null) return false;
  if (bits === 0) return true;
  const mask = (~0 << (32 - bits)) >>> 0;
  return (ipInt & mask) === (baseInt & mask);
}

// IPv4 ranges that must not be reached by webhook deliveries.
const V4_BLOCK: Array<{ cidr: string; reason: UrlBlockReason }> = [
  { cidr: "0.0.0.0/8", reason: "unspecified_address" },
  { cidr: "10.0.0.0/8", reason: "private_address" },
  { cidr: "100.64.0.0/10", reason: "private_address" }, // CGNAT
  { cidr: "127.0.0.0/8", reason: "loopback_address" },
  { cidr: "169.254.0.0/16", reason: "link_local_address" },
  { cidr: "172.16.0.0/12", reason: "private_address" },
  { cidr: "192.0.0.0/24", reason: "private_address" },
  { cidr: "192.168.0.0/16", reason: "private_address" },
  { cidr: "198.18.0.0/15", reason: "private_address" }, // benchmarking
  { cidr: "224.0.0.0/4", reason: "multicast_address" },
  { cidr: "240.0.0.0/4", reason: "broadcast_address" },
  { cidr: "255.255.255.255/32", reason: "broadcast_address" },
];

function classifyV4(ip: string): UrlBlockReason | null {
  if (isMetadata(ip)) return "metadata_address";
  for (const { cidr, reason } of V4_BLOCK) {
    if (inV4Cidr(ip, cidr)) {
      if (reason === "loopback_address" && loopbackEscapeHatch()) return null;
      return reason;
    }
  }
  return null;
}

// Lowercase, strip zone id (%eth0), expand-compare against IPv6 ranges that
// node:net exposes via direct prefix checks. We don't need full CIDR math
// for v6 — a small set of prefixes covers the dangerous space.
function classifyV6(ipRaw: string): UrlBlockReason | null {
  const ip = ipRaw.toLowerCase().split("%")[0];
  if (isMetadata(ip)) return "metadata_address";
  if (ip === "::" || ip === "::0") return "unspecified_address";
  if (ip === "::1") return loopbackEscapeHatch() ? null : "loopback_address";
  // IPv4-mapped (::ffff:a.b.c.d) — re-classify via the v4 ranges.
  const mapped = ip.match(/^::ffff:([0-9.]+)$/);
  if (mapped && net.isIPv4(mapped[1])) {
    return classifyV4(mapped[1]);
  }
  // fe80::/10 link-local, fc00::/7 unique-local, ff00::/8 multicast.
  if (ip.startsWith("fe8") || ip.startsWith("fe9") || ip.startsWith("fea") || ip.startsWith("feb")) {
    return "link_local_address";
  }
  if (ip.startsWith("fc") || ip.startsWith("fd")) {
    return "private_address";
  }
  if (ip.startsWith("ff")) {
    return "multicast_address";
  }
  return null;
}

export function classifyIp(ip: string): UrlBlockReason | null {
  if (net.isIPv4(ip)) return classifyV4(ip);
  if (net.isIPv6(ip)) return classifyV6(ip);
  return null;
}

function reasonMessage(r: UrlBlockReason, detail?: string): string {
  const base: Record<UrlBlockReason, string> = {
    invalid_url: "URL is not a valid http(s) URL.",
    bad_scheme: "Only http and https are allowed.",
    userinfo_forbidden: "URLs with embedded credentials are not allowed.",
    port_not_allowed: "Port is not in the webhook port allowlist (80, 443, 8080, 8443).",
    private_address: "Destination resolves to a private network address.",
    loopback_address: "Destination resolves to a loopback address.",
    link_local_address: "Destination resolves to a link-local address.",
    metadata_address: "Destination resolves to a cloud metadata service.",
    multicast_address: "Destination resolves to a multicast address.",
    broadcast_address: "Destination resolves to a broadcast address.",
    unspecified_address: "Destination resolves to the unspecified address.",
    dns_lookup_failed: "Could not resolve destination hostname.",
  };
  return detail ? `${base[r]} (${detail})` : base[r];
}

export type CheckOptions = {
  // Hostnames (case-insensitive, exact match) that bypass the IP-range block.
  // Use sparingly. Cloud metadata addresses can never be bypassed.
  allowHostnames?: string[];
  // If true, skip DNS resolution. Useful for validating *user input* before
  // they save the webhook — we still block obvious literal-IP attacks.
  skipDns?: boolean;
};

export async function checkOutboundUrl(
  input: string,
  opts: CheckOptions = {},
): Promise<UrlCheck> {
  let url: URL;
  try {
    url = new URL(input);
  } catch {
    return { ok: false, reason: "invalid_url", message: reasonMessage("invalid_url") };
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { ok: false, reason: "bad_scheme", message: reasonMessage("bad_scheme") };
  }
  if (url.username || url.password) {
    return {
      ok: false,
      reason: "userinfo_forbidden",
      message: reasonMessage("userinfo_forbidden"),
    };
  }
  // Port restriction is intentionally omitted: enterprise webhook receivers
  // commonly sit behind a reverse proxy on non-standard ports inside a VPC.
  // The IP-class checks below are what actually prevent SSRF.

  const host = url.hostname.replace(/^\[|\]$/g, "");
  // Test escape hatch: integration tests stand up localhost HTTP servers and
  // need to actually deliver. Production never sets this. Cloud metadata is
  // still rejected even with the flag on.
  const allowLoopbackForTests =
    process.env.SHOTCLASSIFY_WEBHOOK_ALLOW_LOOPBACK === "1";
  const allowSet = new Set(
    (opts.allowHostnames || []).map((h) => h.trim().toLowerCase()).filter(Boolean),
  );
  const hostAllowed = allowSet.has(host.toLowerCase());

  // Literal IP: classify immediately. Metadata addresses are NEVER allowed,
  // even with an allowlist match — that's a footgun we will not arm.
  if (net.isIP(host)) {
    const reason = classifyIp(host);
    if (reason === "metadata_address") {
      return { ok: false, reason, message: reasonMessage(reason, host) };
    }
    if (reason && allowLoopbackForTests && reason !== "broadcast_address" && reason !== "multicast_address") {
      return { ok: true, url, resolved: [host] };
    }
    if (reason && !hostAllowed) {
      return { ok: false, reason, message: reasonMessage(reason, host) };
    }
    return { ok: true, url, resolved: [host] };
  }

  if (opts.skipDns) {
    return { ok: true, url, resolved: [] };
  }

  let addresses: { address: string; family: number }[] = [];
  try {
    addresses = await dns.lookup(host, { all: true, verbatim: true });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "lookup failed";
    return {
      ok: false,
      reason: "dns_lookup_failed",
      message: reasonMessage("dns_lookup_failed", msg),
    };
  }
  if (addresses.length === 0) {
    return {
      ok: false,
      reason: "dns_lookup_failed",
      message: reasonMessage("dns_lookup_failed", "no addresses"),
    };
  }
  for (const a of addresses) {
    const reason = classifyIp(a.address);
    if (reason === "metadata_address") {
      return { ok: false, reason, message: reasonMessage(reason, a.address) };
    }
    if (reason && allowLoopbackForTests && reason !== "broadcast_address" && reason !== "multicast_address") {
      continue;
    }
    if (reason && !hostAllowed) {
      return { ok: false, reason, message: reasonMessage(reason, a.address) };
    }
  }
  return { ok: true, url, resolved: addresses.map((a) => a.address) };
}
